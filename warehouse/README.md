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
- **Baseline test** (`tests/baseline_*.sql`): measures a condition that is true of today's data and should not be. It warns while its count is above zero and fails the build if the count rises above its ceiling in `dbt_project.yml` (`baseline_max`). A count may fall. Raising a ceiling is a deliberate edit.
- **Partial parsing**: dbt can reuse a cached parse and leave tests out of a run. It is switched off in `dbt_project.yml` so that no test is silently left out.

## Environment

`warehouse\.venv` holds dbt. Recreate it with:

    python -m venv warehouse\.venv
    warehouse\.venv\Scripts\python.exe -m pip install -r warehouse\requirements.txt

Never install dbt into the machine's shared `python`.

## The filed layer (a second source)

A **source** is data dbt reads but does not build. Besides the pipeline's `data/output/` files, there is now
a second one: `warehouse/data/filed/`. A separate parser (`warehouse/filed_parser/`) reads each cached SEC
filing once and writes Parquet tables describing what was filed, nothing interpreted. Spec:
`docs/filed_layer.md`. dbt reads those files as source `filed` (staging views `stg_filed_*`).

Run the parser first, then dbt:

    .\warehouse\parse.ps1            # skips filings already parsed; --reparse after a parser change
    .\warehouse\dbt.ps1 build

What the new tests measure (`tests/filed_*.sql` must return nothing; `tests/baseline_filed_*.sql` warn):

- Structure: keys are unique, every link (fact to context, placement to table row, footnote to fact) points at something that exists, placements agree with their facts on concept and context, and every filing folder has one manifest whose row counts equal the table rows (a missing or empty table file fails).
- Bridge to the old pipeline: does each published holdings row's filing and context exist in the filed layer, does its fair value equal the filed fair-value fact, and how many position facts sit in no table row. Measured counts and their causes are in `docs/baseline_filed_2026-11-18.md`.

A passing build means the tables are internally consistent and their row counts tie to the manifests. The bridge tests measure where the filed layer differs from the old extractor (2,009 published rows have no fair-value fact on their context, 896 position facts sit in no table row, 2 values differ). Neither shows the data is right: passing tests do not mean the data is correct.
