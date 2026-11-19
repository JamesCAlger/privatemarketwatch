# Step 1: Position-Level Marts in dbt - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small dbt project in `warehouse/` that reads today's pipeline outputs for the five v0.5 funds and produces the position-level marts (two fact tables, six dimensions) with tests that measure today's data.

**Architecture:** dbt on DuckDB. Staging models are thin views over the existing Parquet and CSV files in `data/output/`; they are the seam that later steps re-point. Mart models are tables in a local DuckDB file under `warehouse/target/`. Nothing in `data/output/`, `pipeline/` or the frontend is written or changed.

**Tech Stack:** dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3, in the isolated environment `warehouse/.venv` (already created). Windows, PowerShell.

**Spec:** `warehouse/docs/design.md` and `warehouse/docs/marts_columns.md` (Task 1 copies them from `scratch/2026-11-18_data_model/`, which is git-ignored). The column lists in `marts_columns.md` are authoritative; this plan implements them.

## Global Constraints

- Scope is the five v0.5 funds only. The list is read from `data/reference/quarter_acceptance_thresholds.json` (`findings_scope.ciks`); never hard-code it.
- Position-level figures only. No fund-level series, returns, industry-breakdown or data-quality marts in this step.
- Read-only on everything outside `warehouse/`. No write to `data/output/`, `frontend/public/data/`, `pipeline/`, `scripts/`, `tests/` or `AGENTS.md`. The one exception is appending an entry to `docs/agent_changelog.md` in Task 6.
- No temporary rules: sector and class stay on the fact table as read. Do not add a "pick one" rule to a dimension.
- Never `pip install` into the machine's `python` (the shared miniconda base). Use `warehouse\.venv\Scripts\python.exe` only.
- Run dbt only through `warehouse\dbt.ps1`. It switches telemetry off and sets the working directory; the project's relative paths depend on that.
- Do not run dbt while a batch build or `rebuild_outputs.py` is running: it reads files those jobs rewrite.
- No network calls. No SEC downloads.
- No inline Python (`python -`, `python -c` snippets for diagnostics). Use `dbt show --inline` for ad-hoc queries.
- Git: the working tree is dirty with other work. Stage only the exact paths a step names. Never `git add -A`, never `git stash`. Commit only when the owner has said to; if they have not, leave the step's files uncommitted and say so.
- ASCII only in any file that is printed to a Windows console.
- Expected test results below were measured on the build of 15-16 November 2026 (batch `b1116a`). If the build of record has changed, a different count is a result to record, not a defect to fix.

## File Structure

```
warehouse/
  .gitignore                     exists: ignores .venv, target, logs, *.duckdb
  .venv/                         exists: dbt environment (not tracked)
  requirements.txt               pinned versions of the environment
  dbt.ps1                        the only way to run dbt
  dbt_project.yml                project settings, paths to pipeline outputs
  profiles.yml                   where dbt builds: target/warehouse.duckdb
  README.md                      how to run, plain-language dbt glossary
  docs/                          design.md, marts_columns.md, this plan, baseline
  scripts/make_manager_brand_seed.py   writes seeds/manager_brand.csv from pipeline/config.py
  seeds/manager_brand.csv        fund -> manager brand
  seeds/_seeds.yml
  models/staging/_sources.yml    declares the pipeline files dbt reads
  models/staging/_staging.yml    tests on staging
  models/staging/stg_*.sql       one thin view per pipeline file
  models/marts/_marts.yml        tests and column docs for the marts
  models/marts/dim_*.sql, fact_*.sql
  tests/*.sql                    hand-written tests: integrity and baseline measurements
```

One responsibility per file. Staging models rename and type columns and filter to scope; they contain no business rule. Mart models join and aggregate only.

---

### Task 1: Project scaffold and the holdings staging model

**Files:**
- Create: `warehouse/requirements.txt`, `warehouse/dbt.ps1`, `warehouse/dbt_project.yml`, `warehouse/profiles.yml`, `warehouse/README.md`
- Create: `warehouse/docs/design.md`, `warehouse/docs/marts_columns.md` (copies)
- Create: `warehouse/models/staging/_sources.yml`, `warehouse/models/staging/_staging.yml`
- Create: `warehouse/models/staging/stg_v05_scope.sql`, `warehouse/models/staging/stg_holdings.sql`

**Interfaces:**
- Consumes: `data/output/private_markets_holdings.parquet`; `data/reference/quarter_acceptance_thresholds.json`.
- Produces: model `stg_v05_scope` (column `cik` VARCHAR, 5 rows); model `stg_holdings` (71,477 rows, one per `row_id`, columns listed in Step 5); the command `.\warehouse\dbt.ps1 <dbt arguments>`.

- [ ] **Step 1: Copy the spec into the tracked folder**

```powershell
Copy-Item "scratch\2026-11-18_data_model\design.md" "warehouse\docs\design.md"
Copy-Item "scratch\2026-11-18_data_model\marts_columns.md" "warehouse\docs\marts_columns.md"
```

- [ ] **Step 2: Write `warehouse/requirements.txt`**

```
dbt-core==1.12.7
dbt-duckdb==1.11.1
duckdb==1.4.3
```

- [ ] **Step 3: Write `warehouse/dbt.ps1`**

```powershell
# Runs dbt for this project. Usage: .\warehouse\dbt.ps1 build
# Telemetry is off and the working directory is the project folder, because the
# project's paths to data/output are relative to it.
$env:DBT_SEND_ANONYMOUS_USAGE_STATS = 'false'
Push-Location $PSScriptRoot
try {
    & "$PSScriptRoot\.venv\Scripts\dbt.exe" @args --profiles-dir . --no-version-check
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
```

- [ ] **Step 4: Write `warehouse/dbt_project.yml` and `warehouse/profiles.yml`**

`warehouse/dbt_project.yml`:

```yaml
name: warehouse
version: "0.1.0"
config-version: 2
profile: warehouse

model-paths: ["models"]
seed-paths: ["seeds"]
test-paths: ["tests"]
target-path: "target"
clean-targets: ["target", "dbt_packages"]

flags:
  send_anonymous_usage_stats: false

vars:
  # Paths are relative to the warehouse/ folder (dbt.ps1 runs from there).
  output_dir: "../data/output"
  repo_root: ".."
  # Quarter used by the baseline tests that are measured at one date.
  baseline_date: "2026-03-31"
  # Largest difference between published and filed fair value that still counts as tied, in dollars.
  reconcile_tolerance: 500000

models:
  warehouse:
    staging:
      +materialized: view
    marts:
      +materialized: table

seeds:
  warehouse:
    +column_types:
      cik: varchar

data_tests:
  warehouse:
    # Keep the failing rows of every test in a table, so a failure can be inspected.
    +store_failures: true
```

`warehouse/profiles.yml`:

```yaml
warehouse:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: target/warehouse.duckdb
      threads: 4
```

- [ ] **Step 5: Declare the source and write the tests first**

`warehouse/models/staging/_sources.yml`:

```yaml
version: 2

sources:
  - name: pipeline
    description: Files written by the existing pipeline under data/output. Read-only.
    meta:
      external_location: "{{ var('output_dir') }}/{name}.parquet"
    tables:
      - name: private_markets_holdings
        description: One row per position per fund per report date. 101 columns.
```

`warehouse/models/staging/_staging.yml`:

```yaml
version: 2

models:
  - name: stg_v05_scope
    description: The funds in scope, read from the acceptance thresholds file.
    columns:
      - name: cik
        data_tests:
          - unique
          - not_null

  - name: stg_holdings
    description: Holdings rows for the funds in scope, BDC source only. No business rule.
    columns:
      - name: row_id
        data_tests:
          - unique
          - not_null
      - name: cik
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('stg_v05_scope')
                field: cik
      - name: position_id
        data_tests:
          - not_null
      - name: entity_id
        data_tests:
          - not_null
```

- [ ] **Step 6: Run to see the tests fail**

Run: `.\warehouse\dbt.ps1 build --select staging`
Expected: an error that the models `stg_v05_scope` and `stg_holdings` named in `_staging.yml` are not found (dbt reports the tests as referring to a missing node, or builds nothing). No model exists yet.

- [ ] **Step 7: Write the two models**

`warehouse/models/staging/stg_v05_scope.sql`:

```sql
-- The v0.5 funds. The acceptance thresholds file is the single place this list is kept.
select unnest(findings_scope.ciks) as cik
from read_json('{{ var("repo_root") }}/data/reference/quarter_acceptance_thresholds.json')
```

`warehouse/models/staging/stg_holdings.sql`:

```sql
-- Thin view over the pipeline's holdings file: scope filter, blank text to null, nothing else.
select
    row_id,
    cik,
    report_date,
    accession_number,
    filing_date,
    nullif(bdc_form_type, '')              as form_type,
    position_id,
    entity_id,
    accounting_scope_id,
    accounting_record_class,
    fair_value,
    cost_reported,
    cost,
    principal_amount,
    nullif(principal_amount_currency, '')  as principal_amount_currency,
    principal_amount_usd,
    nullif(principal_fx_status, '')        as principal_fx_status,
    shares_held,
    pct_of_net_assets,
    pct_of_net_assets_calculated,
    interest_rate,
    nullif(interest_rate_kind, '')         as interest_rate_kind,
    interest_rate_reported,
    interest_rate_cash,
    pik_rate,
    basis_spread,
    nullif(basis_spread_kind, '')          as basis_spread_kind,
    nullif(reference_rate_type, '')        as reference_rate_type,
    nullif(reference_rate_source, '')      as reference_rate_source,
    nullif(coupon_type, '')                as coupon_type,
    maturity_date,
    nullif(maturity_precision, '')         as maturity_precision,
    nullif(nonaccrual_status, '')          as nonaccrual_status,
    nonaccrual_footnote,
    nonaccrual_dimension,
    issuer_name,
    nullif(instrument_description, '')     as instrument_description,
    nullif(extracted_industry, '')         as extracted_industry,
    bdc_investment_identifier,
    nullif(asset_category, '')             as asset_category,
    nullif(lien_position, '')              as lien_position,
    nullif(instrument_type, '')            as instrument_type,
    nullif(index_classification, '')       as index_classification,
    nullif(exposure_type, '')              as exposure_type,
    nullif(asset_class, '')                as asset_class,
    nullif(gics_sector, '')                as gics_sector,
    nullif(gics_sub_industry, '')          as gics_sub_industry,
    nullif(corrected_fields, '')           as corrected_fields,
    src_context_id
from {{ source('pipeline', 'private_markets_holdings') }}
where source = 'bdc'
  and cik in (select cik from {{ ref('stg_v05_scope') }})
```

- [ ] **Step 8: Run to see the tests pass, and check the row count**

Run: `.\warehouse\dbt.ps1 build --select staging`
Expected: `PASS=10 WARN=0 ERROR=0` (2 models, 8 tests).

Run: `.\warehouse\dbt.ps1 show --inline "select count(*) as n, count(distinct cik) as funds, min(report_date) as d0, max(report_date) as d1 from {{ ref('stg_holdings') }}"`
Expected: `n = 71477`, `funds = 5`, `d0 = 2022-09-30`, `d1 = 2026-06-30`.

- [ ] **Step 9: Write `warehouse/README.md`**

```markdown
# warehouse

A dbt project that turns the pipeline's outputs into position-level marts for the five v0.5 funds.
It only reads `data/output/`. It builds into `warehouse/target/warehouse.duckdb`, which is not tracked.

## Run

    .\warehouse\dbt.ps1 build            # build every model and run every test
    .\warehouse\dbt.ps1 build --select staging
    .\warehouse\dbt.ps1 show --inline "select * from {{ ref('dim_fund') }}"

Do not run it while a batch build or rebuild is running.

## Words dbt uses

- **Source**: a file or table dbt reads but does not build. Ours are the pipeline's Parquet and CSV files, declared in `models/staging/_sources.yml`.
- **Model**: one SQL `select` in one `.sql` file. dbt turns it into a view or a table and works out the build order from the `ref()` and `source()` calls inside it.
- **Staging model** (`stg_`): a thin view over one source. It renames, types and filters. It holds no business rule. Later steps swap what a staging model reads without touching the marts.
- **Mart**: a table meant to be queried: a fact table (`fact_`, the measurements) or a dimension (`dim_`, the things being measured).
- **Seed**: a small CSV kept in the project and loaded as a table. Ours is `seeds/manager_brand.csv`.
- **Test**: a query that must return no rows. Generic tests (`unique`, `not_null`, `relationships`) are declared in the `.yml` files; hand-written ones are the `.sql` files in `tests/`.
- **Severity**: a test set to `warn` reports a count without failing the build. The baseline tests use it: they measure known faults in today's data.

## Environment

`warehouse\.venv` holds dbt. Recreate it with:

    python -m venv warehouse\.venv
    warehouse\.venv\Scripts\python.exe -m pip install -r warehouse\requirements.txt

Never install dbt into the machine's shared `python`.
```

- [ ] **Step 10: Commit (only with the owner's go)**

```powershell
git add warehouse/.gitignore warehouse/requirements.txt warehouse/dbt.ps1 warehouse/dbt_project.yml warehouse/profiles.yml warehouse/README.md warehouse/docs warehouse/models/staging/_sources.yml warehouse/models/staging/_staging.yml warehouse/models/staging/stg_v05_scope.sql warehouse/models/staging/stg_holdings.sql
git commit -m "Add dbt warehouse scaffold and holdings staging model" -m "- New warehouse/ dbt project (dbt-core 1.12.7, dbt-duckdb 1.11.1) reading data/output read-only
- stg_holdings: the five v0.5 funds, scope read from the acceptance thresholds file
- Design and mart column spec copied into warehouse/docs"
```

---

### Task 2: Remaining staging models and the manager-brand seed

**Files:**
- Modify: `warehouse/models/staging/_sources.yml`, `warehouse/models/staging/_staging.yml`
- Create: `warehouse/models/staging/stg_position_pik_status.sql`, `stg_cost_donor_audit.sql`, `stg_entity_lookup.sql`, `stg_fund_financials.sql`, `stg_bdc_universe.sql`, `stg_filings_index.sql`, `stg_cohort.sql`
- Create: `warehouse/scripts/make_manager_brand_seed.py`, `warehouse/seeds/manager_brand.csv`, `warehouse/seeds/_seeds.yml`

**Interfaces:**
- Consumes: `stg_v05_scope(cik)`, `stg_holdings` from Task 1.
- Produces (all filtered to the funds in scope unless noted):
  - `stg_position_pik_status(cik, report_date, position_id, pik_current_status, pik_terms_flag)`, unique on the first three
  - `stg_cost_donor_audit(row_id, cost_method)`, unique on `row_id`
  - `stg_entity_lookup(entity_id, canonical_name, alias_count)`, unique on `entity_id`, every borrower in the pipeline
  - `stg_fund_financials(cik, report_date, fund_name_raw, total_assets, net_assets, investments_at_fair_value)`, unique on `cik, report_date`
  - `stg_bdc_universe(cik, vehicle_type, status, bdc_election_date, first_filing_date)`, unique on `cik`
  - `stg_filings_index(accession_number, primary_document)`, unique on `accession_number`
  - `stg_cohort(cik, cohort_status)`, every fund in the cohort manifest
  - seed `manager_brand(cik, manager_brand)`, 142 rows

- [ ] **Step 1: Add the sources**

Replace the `tables:` list in `warehouse/models/staging/_sources.yml` with:

```yaml
    tables:
      - name: private_markets_holdings
        description: One row per position per fund per report date. 101 columns.
      - name: position_pik_status
        description: PIK status per holding. Its own key is a row number; join on fund, date and position.
      - name: cost_donor_audit
        description: Per holdings row, whether the cost is reported or not filed.
      - name: entity_lookup
        description: One row per borrower name variant.
      - name: fund_financials
        description: Fund-level balance sheet per quarter. CSV, all text.
        meta:
          external_location: "read_csv('{{ var('output_dir') }}/fund_financials.csv', header=true, all_varchar=true)"
      - name: bdc_universe
        description: One row per BDC. CSV, all text.
        meta:
          external_location: "read_csv('{{ var('output_dir') }}/bdc_universe.csv', header=true, all_varchar=true)"
      - name: bdc_filings_index
        description: Filing metadata. CSV, all text. Has duplicate rows per accession.
        meta:
          external_location: "read_csv('{{ var('output_dir') }}/bdc_filings_index.csv', header=true, all_varchar=true)"
```

- [ ] **Step 2: Write the tests first**

Append to the `models:` list in `warehouse/models/staging/_staging.yml`:

```yaml
  - name: stg_position_pik_status
    columns:
      - name: position_id
        data_tests:
          - not_null

  - name: stg_cost_donor_audit
    columns:
      - name: row_id
        data_tests:
          - unique
          - not_null
          - relationships:
              arguments:
                to: ref('stg_holdings')
                field: row_id
      - name: cost_method
        data_tests:
          - accepted_values:
              arguments:
                values: ['reported', 'not_filed']

  - name: stg_entity_lookup
    columns:
      - name: entity_id
        data_tests:
          - unique
          - not_null

  - name: stg_fund_financials
    columns:
      - name: cik
        data_tests:
          - not_null

  - name: stg_bdc_universe
    columns:
      - name: cik
        data_tests:
          - unique
          - not_null

  - name: stg_filings_index
    columns:
      - name: accession_number
        data_tests:
          - unique
          - not_null

  - name: stg_cohort
    columns:
      - name: cik
        data_tests:
          - unique
          - not_null
      - name: cohort_status
        data_tests:
          - accepted_values:
              arguments:
                values: ['active', 'deferred', 'held_back']
```

Create `warehouse/seeds/_seeds.yml`:

```yaml
version: 2

seeds:
  - name: manager_brand
    description: Fund to manager brand. Generated from CIK_TO_MANAGER_BRAND in pipeline/config.py by scripts/make_manager_brand_seed.py. A brand, not the registered adviser.
    columns:
      - name: cik
        data_tests:
          - unique
          - not_null
      - name: manager_brand
        data_tests:
          - not_null
```

Create two hand-written tests for the composite keys.

`warehouse/tests/stg_position_pik_status_key_unique.sql`:

```sql
-- One PIK status row per fund, date and position.
select cik, report_date, position_id, count(*) as n
from {{ ref('stg_position_pik_status') }}
group by 1, 2, 3
having count(*) > 1
```

`warehouse/tests/stg_fund_financials_key_unique.sql`:

```sql
-- One financials row per fund and date.
select cik, report_date, count(*) as n
from {{ ref('stg_fund_financials') }}
group by 1, 2
having count(*) > 1
```

- [ ] **Step 3: Run to see them fail**

Run: `.\warehouse\dbt.ps1 build --select staging`
Expected: errors naming the seven models and the seed as not found.

- [ ] **Step 4: Write the seed generator and run it**

`warehouse/scripts/make_manager_brand_seed.py`:

```python
"""Write warehouse/seeds/manager_brand.csv from CIK_TO_MANAGER_BRAND in pipeline/config.py.

Run with the machine's python from the repository root (it needs the pipeline package):

    python warehouse/scripts/make_manager_brand_seed.py

The mapping lives in Python; dbt reads tables. Until the website export reads this file too, the
two copies can drift: rerun this after any change to the mapping.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.config import CIK_TO_MANAGER_BRAND  # noqa: E402

OUT = ROOT / "warehouse" / "seeds" / "manager_brand.csv"


def main() -> int:
    rows = sorted((str(cik).zfill(10), brand) for cik, brand in CIK_TO_MANAGER_BRAND.items())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["cik", "manager_brand"])
        writer.writerows(rows)
    print("wrote %d rows to %s" % (len(rows), OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `python warehouse/scripts/make_manager_brand_seed.py`
Expected: `wrote 142 rows to ...\warehouse\seeds\manager_brand.csv`

- [ ] **Step 5: Write the seven staging models**

`warehouse/models/staging/stg_position_pik_status.sql`:

```sql
select
    cik,
    report_date,
    position_id,
    nullif(pik_current_status, '') as pik_current_status,
    pik_terms_flag
from {{ source('pipeline', 'position_pik_status') }}
where cik in (select cik from {{ ref('stg_v05_scope') }})
```

`warehouse/models/staging/stg_cost_donor_audit.sql`:

```sql
select
    a.row_id,
    a.method as cost_method
from {{ source('pipeline', 'cost_donor_audit') }} a
where a.row_id in (select row_id from {{ ref('stg_holdings') }})
```

`warehouse/models/staging/stg_entity_lookup.sql`:

```sql
-- The lookup has one row per name variant; a borrower has one canonical name.
select
    entity_id,
    min(canonical_name)                 as canonical_name,
    count(distinct issuer_name_variant) as alias_count
from {{ source('pipeline', 'entity_lookup') }}
group by 1
```

`warehouse/models/staging/stg_fund_financials.sql`:

```sql
select
    lpad(cik, 10, '0')                                   as cik,
    try_cast(report_date as date)                        as report_date,
    entity_name                                          as fund_name_raw,
    try_cast(total_assets as double)                     as total_assets,
    try_cast(net_assets as double)                       as net_assets,
    try_cast(investments_at_fair_value as double)        as investments_at_fair_value
from {{ source('pipeline', 'fund_financials') }}
where lpad(cik, 10, '0') in (select cik from {{ ref('stg_v05_scope') }})
```

`warehouse/models/staging/stg_bdc_universe.sql`:

```sql
select
    lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') as cik,
    nullif(vehicle_type, '')                              as vehicle_type,
    nullif(status, '')                                    as status,
    try_cast(election_date as date)                       as bdc_election_date,
    try_cast(first_filing_date as date)                   as first_filing_date
from {{ source('pipeline', 'bdc_universe') }}
where lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') in (select cik from {{ ref('stg_v05_scope') }})
```

`warehouse/models/staging/stg_filings_index.sql`:

```sql
-- The index repeats accessions; the primary document does not differ within one.
select
    accession_number,
    min(primary_document) as primary_document
from {{ source('pipeline', 'bdc_filings_index') }}
where accession_number in (select accession_number from {{ ref('stg_holdings') }})
group by 1
```

`warehouse/models/staging/stg_cohort.sql`:

```sql
-- Cohort manifest: active entries, deferred entries and held-back funds.
with manifest as (
    select *
    from read_json('{{ var("repo_root") }}/data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json')
)
select e.cik as cik, 'active' as cohort_status
from manifest, unnest(manifest.entries) as t(e)
union all
select e.cik, 'deferred'
from manifest, unnest(manifest.deferred_entries) as t(e)
union all
select c, 'held_back'
from manifest, unnest(manifest.held_back_ciks) as t(c)
```

- [ ] **Step 6: Run to see everything pass**

Run: `.\warehouse\dbt.ps1 build --select staging manager_brand`
Expected: `ERROR=0`, `WARN=0`.

Run: `.\warehouse\dbt.ps1 show --inline "select (select count(*) from {{ ref('stg_position_pik_status') }}) as pik, (select count(*) from {{ ref('stg_cost_donor_audit') }}) as cost_rows, (select count(*) from {{ ref('stg_fund_financials') }}) as fin, (select count(*) from {{ ref('stg_bdc_universe') }}) as universe, (select count(*) from {{ ref('stg_filings_index') }}) as filings, (select count(*) from {{ ref('manager_brand') }}) as brands"`
Expected: `pik = 71477`, `cost_rows = 71477`, `fin = 114`, `universe = 5`, `filings = 74`, `brands = 142`.

If `stg_cohort` fails its `unique` test, a fund is listed under two statuses in the manifest: report the fund and stop; do not deduplicate.

- [ ] **Step 7: Commit (only with the owner's go)**

```powershell
git add warehouse/models/staging warehouse/seeds warehouse/scripts/make_manager_brand_seed.py warehouse/tests/stg_position_pik_status_key_unique.sql warehouse/tests/stg_fund_financials_key_unique.sql
git commit -m "Add remaining staging models and manager-brand seed" -m "- Seven staging views over pipeline outputs (PIK status, cost audit, entity lookup, fund financials, universe, filing index, cohort)
- manager_brand seed generated from CIK_TO_MANAGER_BRAND
- Key and reference tests on each"
```

---

### Task 3: Dimensions

**Files:**
- Create: `warehouse/models/marts/dim_date.sql`, `dim_filing.sql`, `dim_adviser.sql`, `dim_fund.sql`, `dim_entity.sql`, `dim_position.sql`
- Create: `warehouse/models/marts/_marts.yml`

**Interfaces:**
- Consumes: every model and the seed from Tasks 1 and 2.
- Produces:
  - `dim_date(report_date, year, quarter, quarter_label)`: 16 rows
  - `dim_filing(accession_number, cik, form_type, filing_date, report_date, is_amendment, primary_document)`: 74 rows
  - `dim_adviser(adviser_id, manager_brand)`: 5 rows
  - `dim_fund(cik, fund_name, adviser_id, vehicle_type, status, bdc_election_date, first_filing_date, cohort_status, is_v05)`: 5 rows
  - `dim_entity(entity_id, canonical_name, alias_count, first_seen_date, last_seen_date)`: 3,567 rows
  - `dim_position(position_id, cik, accounting_scope_id, entity_id_latest, anchor_row_id, first_report_date, last_report_date, observation_count, issuer_name_latest, instrument_description_latest)`: 15,154 rows

`adviser_id` is the brand in lower case with spaces replaced by underscores (`blue_owl`).

- [ ] **Step 1: Write the tests first**

`warehouse/models/marts/_marts.yml`:

```yaml
version: 2

models:
  - name: dim_date
    description: One row per report date in scope.
    columns:
      - name: report_date
        data_tests:
          - unique
          - not_null

  - name: dim_filing
    description: One row per filing used by the holdings in scope.
    columns:
      - name: accession_number
        data_tests:
          - unique
          - not_null
      - name: cik
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_fund')
                field: cik
      - name: form_type
        data_tests:
          - not_null

  - name: dim_adviser
    description: One row per manager brand of a fund in scope. A brand, not the registered adviser.
    columns:
      - name: adviser_id
        data_tests:
          - unique
          - not_null

  - name: dim_fund
    description: One row per fund in scope.
    columns:
      - name: cik
        data_tests:
          - unique
          - not_null
      - name: fund_name
        data_tests:
          - not_null
      - name: adviser_id
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_adviser')
                field: adviser_id
      - name: cohort_status
        data_tests:
          - not_null

  - name: dim_entity
    description: One row per borrower held by a fund in scope. Sector is not here in step 1; it is on the fact as read.
    columns:
      - name: entity_id
        data_tests:
          - unique
          - not_null
      - name: canonical_name
        data_tests:
          - not_null

  - name: dim_position
    description: One row per position. Class is not here in step 1; it is on the fact as read.
    columns:
      - name: position_id
        data_tests:
          - unique
          - not_null
      - name: cik
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_fund')
                field: cik
      - name: anchor_row_id
        data_tests:
          - unique
          - not_null
```

- [ ] **Step 2: Run to see them fail**

Run: `.\warehouse\dbt.ps1 build --select marts`
Expected: errors naming the six dimension models as not found.

- [ ] **Step 3: Write the six models**

`warehouse/models/marts/dim_date.sql`:

```sql
select
    report_date,
    year(report_date)                                                        as year,
    quarter(report_date)                                                     as quarter,
    strftime(report_date, '%Y') || 'q' || cast(quarter(report_date) as varchar) as quarter_label
from (select distinct report_date from {{ ref('stg_holdings') }})
```

`warehouse/models/marts/dim_filing.sql`:

```sql
-- One filing per accession. A handful of rows carry a different form type from the rest of
-- their filing (see tests/baseline_filing_single_form_type.sql); the most common value is used.
select
    h.accession_number,
    min(h.cik)                    as cik,
    mode(h.form_type)             as form_type,
    max(h.filing_date)            as filing_date,
    mode(h.report_date)           as report_date,
    mode(h.form_type) like '%/A'  as is_amendment,
    min(f.primary_document)       as primary_document
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_filings_index') }} f on f.accession_number = h.accession_number
group by 1
```

`warehouse/models/marts/dim_adviser.sql`:

```sql
select distinct
    lower(replace(b.manager_brand, ' ', '_')) as adviser_id,
    b.manager_brand
from {{ ref('manager_brand') }} b
where b.cik in (select cik from {{ ref('stg_v05_scope') }})
```

`warehouse/models/marts/dim_fund.sql`:

```sql
-- Fund name: the same source and rule as the website. The financials file's name at the fund's
-- latest quarter with total assets, with any "(CIK 0001234567)" suffix removed.
with latest_name as (
    select
        cik,
        arg_max(fund_name_raw, report_date) as fund_name_raw
    from {{ ref('stg_fund_financials') }}
    where total_assets > 0
    group by 1
)
select
    s.cik,
    trim(regexp_replace(regexp_replace(n.fund_name_raw, '\s*\(CIK\s+\d+\)\s*', ' ', 'g'), '\s+', ' ', 'g')) as fund_name,
    lower(replace(b.manager_brand, ' ', '_')) as adviser_id,
    u.vehicle_type,
    u.status,
    u.bdc_election_date,
    u.first_filing_date,
    c.cohort_status,
    true as is_v05
from {{ ref('stg_v05_scope') }} s
left join latest_name n                on n.cik = s.cik
left join {{ ref('manager_brand') }} b on b.cik = s.cik
left join {{ ref('stg_bdc_universe') }} u on u.cik = s.cik
left join {{ ref('stg_cohort') }} c    on c.cik = s.cik
```

`warehouse/models/marts/dim_entity.sql`:

```sql
select
    h.entity_id,
    l.canonical_name,
    l.alias_count,
    min(h.report_date) as first_seen_date,
    max(h.report_date) as last_seen_date
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_entity_lookup') }} l on l.entity_id = h.entity_id
group by 1, 2, 3
```

`warehouse/models/marts/dim_position.sql`:

```sql
-- A position never spans funds or accounting scopes (verified on the build of 2026-11-16).
-- It can span two borrower ids, so the borrower here is the latest one and is named as such.
select
    position_id,
    min(cik)                                    as cik,
    min(accounting_scope_id)                    as accounting_scope_id,
    arg_max(entity_id, report_date)             as entity_id_latest,
    arg_min(row_id, report_date)                as anchor_row_id,
    min(report_date)                            as first_report_date,
    max(report_date)                            as last_report_date,
    count(*)                                    as observation_count,
    arg_max(issuer_name, report_date)           as issuer_name_latest,
    arg_max(instrument_description, report_date) as instrument_description_latest
from {{ ref('stg_holdings') }}
group by 1
```

- [ ] **Step 4: Run to see them pass, and check the row counts**

Run: `.\warehouse\dbt.ps1 build --select marts`
Expected: `ERROR=0`, `WARN=0`.

Run: `.\warehouse\dbt.ps1 show --inline "select (select count(*) from {{ ref('dim_date') }}) as dates, (select count(*) from {{ ref('dim_filing') }}) as filings, (select count(*) from {{ ref('dim_adviser') }}) as advisers, (select count(*) from {{ ref('dim_fund') }}) as funds, (select count(*) from {{ ref('dim_entity') }}) as entities, (select count(*) from {{ ref('dim_position') }}) as positions"`
Expected: `dates = 16`, `filings = 74`, `advisers = 5`, `funds = 5`, `entities = 3567`, `positions = 15154`.

Run: `.\warehouse\dbt.ps1 show --inline "select cik, fund_name, adviser_id, cohort_status from {{ ref('dim_fund') }} order by cik"`
Expected fund names: `ARES CAPITAL CORP`, `Blackstone Private Credit Fund`, `Blue Owl Credit Income Corp.`, `Apollo Debt Solutions BDC`, `HPS Corporate Lending Fund`; advisers `ares`, `blackstone`, `blue_owl`, `apollo`, `hps`; all `active`.

- [ ] **Step 5: Commit (only with the owner's go)**

```powershell
git add warehouse/models/marts
git commit -m "Add dimension tables to the warehouse marts" -m "- dim_date, dim_filing, dim_adviser, dim_fund, dim_entity, dim_position for the five v0.5 funds
- Fund name uses the website's source and rule; adviser is the curated manager brand
- Sector and class are deliberately not on the dimensions in step 1"
```

---

### Task 4: fact_observation

**Files:**
- Create: `warehouse/models/marts/fact_observation.sql`
- Modify: `warehouse/models/marts/_marts.yml`
- Create: `warehouse/tests/fact_observation_matches_staging.sql`, `warehouse/tests/fact_observation_grain.sql`

**Interfaces:**
- Consumes: `stg_holdings`, `stg_position_pik_status`, `stg_cost_donor_audit`, and the dimensions from Task 3.
- Produces: `fact_observation`, 71,477 rows, one per `row_id`, with exactly the columns in the `fact_observation` table of `warehouse/docs/marts_columns.md`.

- [ ] **Step 1: Write the tests first**

Append to the `models:` list in `warehouse/models/marts/_marts.yml`:

```yaml
  - name: fact_observation
    description: One position, one fund, one report date. Sector and class are held here as read.
    columns:
      - name: row_id
        data_tests:
          - unique
          - not_null
      - name: cik
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_fund')
                field: cik
      - name: report_date
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_date')
                field: report_date
      - name: accession_number
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_filing')
                field: accession_number
      - name: position_id
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_position')
                field: position_id
      - name: entity_id
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_entity')
                field: entity_id
      - name: is_published
        data_tests:
          - not_null
      - name: fair_value
        data_tests:
          - not_null
```

`warehouse/tests/fact_observation_matches_staging.sql`:

```sql
-- The fact must hold exactly the staged rows: same count, same total fair value.
-- A join that duplicated or dropped rows would show here.
with staged as (
    select count(*) as n, sum(fair_value) as fv from {{ ref('stg_holdings') }}
),
fact as (
    select count(*) as n, sum(fair_value) as fv from {{ ref('fact_observation') }}
)
select staged.n as staged_rows, fact.n as fact_rows, staged.fv as staged_fv, fact.fv as fact_fv
from staged, fact
where staged.n <> fact.n
   or abs(staged.fv - fact.fv) > 0.005
```

`warehouse/tests/fact_observation_grain.sql`:

```sql
-- At most one observation per fund, date, accounting scope and position.
select cik, report_date, accounting_scope_id, position_id, count(*) as n
from {{ ref('fact_observation') }}
group by 1, 2, 3, 4
having count(*) > 1
```

- [ ] **Step 2: Run to see them fail**

Run: `.\warehouse\dbt.ps1 build --select fact_observation`
Expected: an error that `fact_observation` is not found.

- [ ] **Step 3: Write the model**

`warehouse/models/marts/fact_observation.sql`:

```sql
select
    -- keys
    h.row_id,
    h.cik,
    h.report_date,
    h.accession_number,
    h.position_id,
    h.entity_id,
    h.accounting_scope_id,
    h.accounting_record_class <> 'underlying_schedule' as is_published,
    -- value
    h.fair_value,
    h.cost_reported,
    h.cost,
    c.cost_method = 'not_filed'                        as cost_is_proxy,
    h.principal_amount,
    h.principal_amount_currency,
    h.principal_amount_usd,
    h.principal_fx_status,
    h.shares_held,
    -- share of net assets
    h.pct_of_net_assets                                as pct_of_net_assets_reported,
    h.pct_of_net_assets_calculated,
    -- rate
    h.interest_rate,
    h.interest_rate_kind,
    h.interest_rate_reported,
    h.interest_rate_cash,
    h.pik_rate,
    h.basis_spread,
    h.basis_spread_kind,
    h.reference_rate_type,
    h.reference_rate_source,
    h.coupon_type,
    -- maturity
    h.maturity_date,
    h.maturity_precision,
    -- status
    h.nonaccrual_status,
    h.nonaccrual_footnote,
    h.nonaccrual_dimension,
    p.pik_current_status,
    p.pik_terms_flag,
    -- as filed
    h.issuer_name                                      as issuer_name_as_filed,
    h.instrument_description,
    h.extracted_industry                               as industry_as_filed,
    h.bdc_investment_identifier                        as source_identifier,
    h.src_context_id,
    -- class and sector, as read this quarter
    h.asset_category                                   as asset_category_as_read,
    h.lien_position                                    as lien_position_as_read,
    h.instrument_type                                  as instrument_type_as_read,
    h.index_classification,
    h.exposure_type,
    h.asset_class,
    h.gics_sector                                      as gics_sector_as_read,
    h.gics_sub_industry                                as gics_sub_industry_as_read,
    -- flag
    h.corrected_fields is not null                     as has_correction
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_position_pik_status') }} p
       on p.cik = h.cik and p.report_date = h.report_date and p.position_id = h.position_id
left join {{ ref('stg_cost_donor_audit') }} c
       on c.row_id = h.row_id
```

Note on `cost_is_proxy`: the audit's method is `reported` (69,424 rows) or `not_filed` (2,053 rows) for these funds. Where it is `not_filed`, any value in `cost` is not a filed cost.

- [ ] **Step 4: Run to see them pass**

Run: `.\warehouse\dbt.ps1 build --select fact_observation`
Expected: `ERROR=0`, `WARN=0`.

Run: `.\warehouse\dbt.ps1 show --inline "select count(*) as n, sum(is_published::int) as published_rows, round(sum(case when is_published and report_date = date '2026-03-31' then fair_value end)/1e9, 2) as published_fv_bn_2026q1, sum(cost_is_proxy::int) as proxy_cost_rows, sum(has_correction::int) as corrected_rows from {{ ref('fact_observation') }}"`
Expected: `n = 71477`, `published_rows = 60737`, `proxy_cost_rows = 2053`. Record `published_fv_bn_2026q1` and `corrected_rows` for the baseline in Task 6.

- [ ] **Step 5: Commit (only with the owner's go)**

```powershell
git add warehouse/models/marts/fact_observation.sql warehouse/models/marts/_marts.yml warehouse/tests/fact_observation_matches_staging.sql warehouse/tests/fact_observation_grain.sql
git commit -m "Add fact_observation to the warehouse marts" -m "- One row per position, fund and report date for the five v0.5 funds
- Sector and class kept as read; no pick-one rule
- Tests: key, references to every dimension, grain, and row and value conservation against staging"
```

---

### Task 5: fact_fund_period

**Files:**
- Create: `warehouse/models/marts/fact_fund_period.sql`
- Modify: `warehouse/models/marts/_marts.yml`
- Create: `warehouse/tests/fact_fund_period_grain.sql`

**Interfaces:**
- Consumes: `fact_observation`, `stg_fund_financials`.
- Produces: `fact_fund_period(cik, report_date, accession_number, net_assets, total_assets, investments_at_fair_value_filed, published_fair_value, difference_to_filed)`, 74 rows: one per fund and report date that has holdings.

- [ ] **Step 1: Write the tests first**

Append to the `models:` list in `warehouse/models/marts/_marts.yml`:

```yaml
  - name: fact_fund_period
    description: One fund at one report date. Reconciles the published positions to the fund's filed total. NAV per share and income are deliberately left out until their known defects are fixed.
    columns:
      - name: cik
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_fund')
                field: cik
      - name: report_date
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_date')
                field: report_date
      - name: accession_number
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_filing')
                field: accession_number
      - name: net_assets
        data_tests:
          - not_null
      - name: investments_at_fair_value_filed
        data_tests:
          - not_null
      - name: published_fair_value
        data_tests:
          - not_null
```

`warehouse/tests/fact_fund_period_grain.sql`:

```sql
-- One row per fund and report date.
select cik, report_date, count(*) as n
from {{ ref('fact_fund_period') }}
group by 1, 2
having count(*) > 1
```

- [ ] **Step 2: Run to see them fail**

Run: `.\warehouse\dbt.ps1 build --select fact_fund_period`
Expected: an error that `fact_fund_period` is not found.

- [ ] **Step 3: Write the model**

`warehouse/models/marts/fact_fund_period.sql`:

```sql
-- The filed total comes from the SEC companyfacts record via the pipeline's financials file.
-- It covers the fund's own schedule only, so it is compared with the published basis
-- (rows from a JV's own schedule are excluded).
with published as (
    select
        cik,
        report_date,
        min(accession_number)                                   as accession_number,
        sum(case when is_published then fair_value else 0 end)  as published_fair_value
    from {{ ref('fact_observation') }}
    group by 1, 2
)
select
    p.cik,
    p.report_date,
    p.accession_number,
    f.net_assets,
    f.total_assets,
    f.investments_at_fair_value                                 as investments_at_fair_value_filed,
    p.published_fair_value,
    p.published_fair_value - f.investments_at_fair_value        as difference_to_filed
from published p
left join {{ ref('stg_fund_financials') }} f
       on f.cik = p.cik and f.report_date = p.report_date
```

- [ ] **Step 4: Run to see them pass**

Run: `.\warehouse\dbt.ps1 build --select fact_fund_period`
Expected: `ERROR=0`, `WARN=0`.

Run: `.\warehouse\dbt.ps1 show --limit 80 --inline "select d.fund_name, p.report_date, round(p.investments_at_fair_value_filed/1e6, 1) as filed_m, round(p.published_fair_value/1e6, 1) as published_m, round(p.difference_to_filed/1e6, 1) as diff_m from {{ ref('fact_fund_period') }} p join {{ ref('dim_fund') }} d using (cik) order by 1, 2"`
Expected: 74 rows. Save this output; it is the reconciliation table for the baseline in Task 6. Do not adjust any difference.

- [ ] **Step 5: Commit (only with the owner's go)**

```powershell
git add warehouse/models/marts/fact_fund_period.sql warehouse/models/marts/_marts.yml warehouse/tests/fact_fund_period_grain.sql
git commit -m "Add fact_fund_period to the warehouse marts" -m "- One row per fund and report date: net assets, total assets, filed investment total, published total, difference
- NAV per share and income left out until their known defects are fixed"
```

---

### Task 6: Baseline measurements, record and changelog

These tests measure known faults in today's data. They are set to `warn`: they report a count and do not fail the build. They are not to be made to pass in this step.

**Files:**
- Create: `warehouse/tests/baseline_one_sector_per_borrower.sql`, `baseline_one_asset_category_per_position.sql`, `baseline_one_lien_per_position.sql`, `baseline_one_instrument_type_per_position.sql`, `baseline_one_borrower_per_position.sql`, `baseline_filing_single_form_type.sql`, `baseline_published_equals_filed.sql`
- Create: `warehouse/docs/baseline_2026-11-18.md`
- Modify: `docs/agent_changelog.md` (append only)

**Interfaces:**
- Consumes: `fact_observation`, `fact_fund_period`, `stg_holdings`.
- Produces: seven warning tests, and a baseline document recording their counts.

- [ ] **Step 1: Write the seven tests**

`warehouse/tests/baseline_one_sector_per_borrower.sql`:

```sql
-- Baseline: a borrower should carry one sector. Measured at one date across the funds in scope.
{{ config(severity='warn') }}
select
    entity_id,
    count(distinct gics_sector_as_read)                                as sectors,
    string_agg(distinct gics_sector_as_read, ' / ' order by gics_sector_as_read) as sector_list,
    sum(fair_value)                                                    as fair_value
from {{ ref('fact_observation') }}
where report_date = cast('{{ var("baseline_date") }}' as date)
group by 1
having count(distinct gics_sector_as_read) > 1
```

`warehouse/tests/baseline_one_asset_category_per_position.sql`:

```sql
-- Baseline: a position should keep one asset category across its observations.
{{ config(severity='warn') }}
select position_id, count(distinct asset_category_as_read) as values_seen
from {{ ref('fact_observation') }}
group by 1
having count(distinct asset_category_as_read) > 1
```

`warehouse/tests/baseline_one_lien_per_position.sql`:

```sql
-- Baseline: a position should keep one lien across its observations. Blanks are not counted.
{{ config(severity='warn') }}
select position_id, count(distinct lien_position_as_read) as values_seen
from {{ ref('fact_observation') }}
group by 1
having count(distinct lien_position_as_read) > 1
```

`warehouse/tests/baseline_one_instrument_type_per_position.sql`:

```sql
-- Baseline: a position should keep one instrument type across its observations. Blanks are not counted.
{{ config(severity='warn') }}
select position_id, count(distinct instrument_type_as_read) as values_seen
from {{ ref('fact_observation') }}
group by 1
having count(distinct instrument_type_as_read) > 1
```

`warehouse/tests/baseline_one_borrower_per_position.sql`:

```sql
-- Baseline: a position should belong to one borrower across its observations.
{{ config(severity='warn') }}
select position_id, count(distinct entity_id) as borrowers
from {{ ref('fact_observation') }}
group by 1
having count(distinct entity_id) > 1
```

`warehouse/tests/baseline_filing_single_form_type.sql`:

```sql
-- Baseline: every holdings row of a filing should carry the same form type and report date.
{{ config(severity='warn') }}
select
    accession_number,
    count(distinct form_type)   as form_types,
    count(distinct report_date) as report_dates
from {{ ref('stg_holdings') }}
group by 1
having count(distinct form_type) > 1 or count(distinct report_date) > 1
```

`warehouse/tests/baseline_published_equals_filed.sql`:

```sql
-- Baseline: published fair value should tie to the fund's filed investment total.
{{ config(severity='warn') }}
select cik, report_date, investments_at_fair_value_filed, published_fair_value, difference_to_filed
from {{ ref('fact_fund_period') }}
where abs(difference_to_filed) > {{ var('reconcile_tolerance') }}
```

- [ ] **Step 2: Run the whole project**

Run: `.\warehouse\dbt.ps1 build`
Expected: `ERROR=0`. Warnings from exactly the seven `baseline_` tests, with these counts on the build of 15-16 November 2026:

| Test | Expected warning count |
|---|---|
| `baseline_one_sector_per_borrower` | 132 |
| `baseline_one_asset_category_per_position` | 63 |
| `baseline_one_lien_per_position` | 116 |
| `baseline_one_instrument_type_per_position` | 6 |
| `baseline_one_borrower_per_position` | 210 |
| `baseline_filing_single_form_type` | 1 (Ares, accession 0001287750-25-000020: 3 rows marked 10-K in a 10-Q) |
| `baseline_published_equals_filed` | not measured before this run; record what you get |

A test passing that is expected to warn means the data changed: record it, do not change the test. Any `ERROR` is a defect in this project: fix it before going on.

- [ ] **Step 3: Record the baseline**

Write `warehouse/docs/baseline_2026-11-18.md` with the real figures from Step 2, from Task 4 Step 4 and from Task 5 Step 4. Use this structure and fill every cell from the run output:

```markdown
# Warehouse baseline

Build of record: batch <batch id from data/output/batches/latest.json>, holdings written <timestamp of data/output/private_markets_holdings.parquet>.
dbt run: <date and time>. Command: `.\warehouse\dbt.ps1 build`. Result line: <the "Done. PASS=.. WARN=.. ERROR=.." line>.

These are measurements of today's data. A warning here is a known fault, not a failure of the warehouse.
All tests clean would still not mean the data is correct: no test here detects a changed field meaning,
a wrong rate on the right row, or offsetting errors.

## Row counts

| Table | Rows |
|---|---|
| fact_observation | |
| fact_fund_period | |
| dim_fund | |
| dim_adviser | |
| dim_entity | |
| dim_position | |
| dim_filing | |
| dim_date | |

## Baseline tests

| Test | Count | Expected (2026-11-16 build) |
|---|---|---|
| baseline_one_sector_per_borrower | | 132 |
| baseline_one_asset_category_per_position | | 63 |
| baseline_one_lien_per_position | | 116 |
| baseline_one_instrument_type_per_position | | 6 |
| baseline_one_borrower_per_position | | 210 |
| baseline_filing_single_form_type | | 1 |
| baseline_published_equals_filed | | not measured before |

## Published against filed, by fund and quarter

<the 74-row table from Task 5 Step 4>

## Other figures

- Published fair value at 2026-03-31, five funds: <figure> bn.
- Rows with a correction recorded: <figure>.
- Rows whose cost is not a filed cost: <figure>.
```

- [ ] **Step 4: Append the changelog entry**

Append to the end of `docs/agent_changelog.md` (append only; the file has other uncommitted changes, leave them alone). Fill the three figures from the baseline:

```markdown
## 2026-11-18 - warehouse/: dbt marts for the five v0.5 funds (step 1 of the data-model redesign)

- New top-level folder `warehouse/`: a dbt project (dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3) in its own environment `warehouse/.venv`. Run with `.\warehouse\dbt.ps1 build`. It reads `data/output/` and writes only `warehouse/target/`.
- Models: 9 staging views over existing outputs; marts `fact_observation`, `fact_fund_period`, `dim_fund`, `dim_adviser`, `dim_entity`, `dim_position`, `dim_filing`, `dim_date`. Scope is `findings_scope.ciks` in `data/reference/quarter_acceptance_thresholds.json`.
- No pipeline code, output, schema, test count or frontend file changed. The website still reads the existing exports.
- Tests: key, reference, grain and conservation tests pass. Seven baseline tests report known faults as warnings: <n> borrowers with more than one sector at 2026-03-31, <n> positions with more than one asset category, <n> fund-quarters where published fair value does not tie to the filed total within 0.5M. Full figures in `warehouse/docs/baseline_2026-11-18.md`.
- Design, mart column spec and plan: `warehouse/docs/`. Not covered in this step: fund-level series, returns, industry breakdown, data quality.
- Environment note: `python` on this machine is the shared miniconda base. dbt must not be installed there (an attempt on 2026-11-18 upgraded protobuf and was reverted).
```

- [ ] **Step 5: Confirm nothing outside `warehouse/` and the changelog changed**

Run: `git status --short -- data/output frontend/public/data pipeline scripts tests`
Expected: no line that was not already present before this plan started. (Compare with the `git status` taken at the start of the work; the tree was already dirty.)

Run: `git status --short -- warehouse docs/agent_changelog.md`
Expected: the `warehouse/` files of this plan, and `docs/agent_changelog.md` modified.

- [ ] **Step 6: Commit (only with the owner's go)**

```powershell
git add warehouse/tests warehouse/docs/baseline_2026-11-18.md
git commit -m "Add baseline measurement tests to the warehouse" -m "- Seven warning tests measuring known faults: several sectors per borrower, class changes per position, published against filed
- Baseline figures recorded in warehouse/docs/baseline_2026-11-18.md"
```

The changelog file carries other agents' uncommitted entries. Do not commit it as part of this work unless the owner says how they want it handled.

---

## Self-review notes

- Spec coverage: every column of `fact_observation`, `fact_fund_period` and the six dimensions in `marts_columns.md` has a line in a model (Tasks 3 to 5). The day-one tests table in that file maps to Task 4 (keys, references, grain) and Task 6 (baseline tests).
- Deliberately not built, per the spec: sector on `dim_entity`, class on `dim_position`, NAV per share, income, any fund-level, returns, industry-breakdown or data-quality mart.
- The syntax used here (sources with `external_location`, `read_csv` and `read_json` sources, `arguments:` under generic tests, `severity='warn'`, project-level `store_failures`, `mode()`, `arg_max()`) was run successfully against the installed versions in a throwaway project on 2026-11-18.
