# warehouse

A dbt project that turns the pipeline's outputs into position-level marts for the five v0.5 funds.
It reads `data/output/`, the filed layer and the readings (below), and writes nothing outside
`warehouse/`. It builds into `warehouse/target/warehouse.duckdb`, which is not tracked.

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

## Readings (a third source)

How each filer is read, and the fixes made to single rows, as two tables. A loader
(`warehouse/readings_loader/`) copies them from the new pipeline's wrappers (`warehouse/wrappers/<cik>.json`) and
the two row-correction files into `warehouse/data/readings/`. dbt reads them as source `readings` (staging views
`stg_reading_rule`, `stg_correction`, `stg_reading_not_loaded`, `stg_wrapper_drift`). Spec:
`docs/intermediate_spine.md`.

**Where fund rules are edited.** Owner decision 2026-11-19: the new pipeline keeps its own copy of each v0.5
fund's wrapper in `warehouse/wrappers/`, taken byte for byte from production's `data/overrides/bdc_xbrl_wrappers/`
(hashes in `warehouse/wrappers/_source.json`). From now on the new pipeline's fund rules are edited there: the
old-style `source_encodings` declarations, and the new-style top-level `reading_rules` list (objects with
`target`, `action`, `parameter`, selectors `concept_namespace` (a glob on the filer's own domain) with
`concept_local`, `accession`, `axis`, `member`, `label`, `feature`, optional `valid_from` / `valid_to`, and
`evidence`). Production keeps reading its own wrappers until cutover. A change made to a production wrapper is
not seen here and must be carried into the copy by hand: the loader compares each production wrapper with its
recorded hash (table `wrapper_drift`), and `baseline_production_wrapper_changed` (ceiling 0) fails the build until
the copy is brought up to date and `_source.json` updated.

    .\warehouse\load_readings.ps1    # rewrites the folder; same inputs give the same manifest
    .\warehouse\dbt.ps1 build

- A **rule** says how a filer's tag or label is read (for example: the rate tag holds the all-in rate). It
  carries forward every quarter.
- A **correction** fixes one field on one row of one filing. It does not carry forward.
- `seeds/reading_action.csv` is the closed list of actions a rule may name. A rule naming anything else
  fails the build.
- The loader stops on a wrapper key or entry it does not understand. Nothing is skipped silently.

Nothing in this layer is applied to data yet. A passing build shows the stores were copied faithfully,
not that any rule or fix is right. Counts: `docs/baseline_readings_2026-11-19.md`.

## The intermediate layer (row roles)

The models in `models/intermediate/` read the filed layer and the readings and decide, for every context of
every parsed filing of the five funds, what the row is. They are tables (`int_*`), built after the staging
views. Spec: `docs/intermediate_spine.md` (section 6.2). Counts: `docs/baseline_roles_2026-11-19.md`.

- A **context** is one filed row of facts: a date and the members that say what it is about (for a
  position, the investment identifier, which carries the label).
- A **selected filing** is the one filing that speaks for a fund and quarter (`int_filing_selected`). When
  a quarter has an original and an amendment, the amendment wins if it is full; a cover-only amendment is
  skipped. A quarter it cannot decide (two originals, a partial amendment) is refused, with the reason.
- A **role** is what a context is. Rules are tried in order and the first that fires decides
  (`int_source_row`, with the rule number and a reason on every row):

| Role | Meaning |
|---|---|
| position | A holding: one loan, equity line or fund interest. Published unless it sits in a JV's own schedule, or is cash (published, flagged `is_cash`). |
| aggregate | A total, subtotal, heading or the cash bucket: by its label, or because its fair value equals the rows below it. |
| comparative | A prior-period figure in the same filing. |
| not_schedule | Not a schedule row (no investment identifier, or no fair value). |
| superseded | In a filing that was not selected for its quarter. |
| unresolved | The rules disagree, or a row reads as a position but carries no term (no principal, shares, rate, spread, PIK rate or maturity) and no rule says it is one. Never published; counted by a baseline test. |

- A **general rule** applies to every fund. Text patterns and axes live in `seeds/role_pattern.csv`
  (for example: a label segment starting with "total" is an aggregate).
- A **fund rule** applies to one fund and lives in that fund's wrapper copy, `warehouse/wrappers/<cik>.json`
  (old-style `source_encodings`, new-style `reading_rules`). A fund rule wins over a general one.
  `seeds/reading_action.csv` lists the actions a rule may name.
- **The comparison with production** (`cmp_row_set`): this layer's position rows against production's
  holdings, joined on filing and context. Every row on one side only gets a cause (for example
  `convention`: cash this layer keeps and production drops). Each cause has a ceiling in `dbt_project.yml`.
  Quarters production has not been built with are left out and listed (`cmp_excluded_quarter`).
  Agreement shows the two pipelines agree. It does not show either is right.

After editing a wrapper copy:

    .\warehouse\load_readings.ps1    # the copy into warehouse\data\readings
    .\warehouse\dbt.ps1 build        # roles, comparison and every test

A new fund rule needs `evidence` (the loader stops without it), and a `label_pattern` needs at least one
`label_examples_no_match` (the build fails without it); every listed example is tested against the pattern. A row moving between roles shows in the comparison
counts and the unresolved count, and fails the build if a ceiling is passed.

CI runs a build on an invented fund, without the repository's data: `ci/README.md`.
