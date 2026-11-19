# CI fixture build

A build of the new pipeline on an invented fund, small enough to keep in the repository. It runs in the
`warehouse` job of `.github/workflows/ci.yml` and can be run the same way locally. It needs none of the
repository's data: nothing under `data/` or `warehouse/data/` is read.

## Run

From the repository root, with the Python that has dbt installed beside it:

    warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>

In CI: `python ci/run_fixture_build.py --work "$RUNNER_TEMP/warehouse_ci"` (from `warehouse/`). Without
`--work` it makes a new temporary folder. The folder must be new or empty and outside `data/`,
`warehouse/data/`, `warehouse/target/` and this fixture. Exit code 0 only when every step passes.

## What it does

| Step | Command | Writes to the work folder |
|---|---|---|
| 1 | the filed parser on `fixture/raw/` (`--raw`, `--out`, `--scope-file`) | `filed/` |
| 2 | the readings loader on `fixture/wrappers/`, `fixture/production_wrappers/` and the two fixture row stores | `readings/` |
| 3 | an empty Parquet file with the column names and types in `fixture/output/private_markets_holdings.columns.csv`, and a header-only `fund_financials.csv` | `output/` |
| 4 | `dbt run --select stg_v05_scope stg_holdings stg_fund_financials` | `ci.duckdb` |
| 5 | `dbt build`, selection below, `--indirect-selection cautious` | `ci.duckdb`, `target/`, `logs/` |
| 6 | `dbt test --select test_type:unit path:tests/baseline_production_wrapper_changed.sql` | same |

dbt runs on its own profile target, `ci` (`warehouse/profiles.yml`), whose database file is set by the
script (`WAREHOUSE_CI_DUCKDB`); it never touches `target/warehouse.duckdb`. Every path reaches dbt through
`--vars` (`filed_dir`, `readings_dir`, `thresholds_file`, `output_dir`); no model is edited. The script
also passes `ci_fixture: true`, which switches on `tests/ci_fixture_expected_roles.sql`, and sets
`DBT_SEND_ANONYMOUS_USAGE_STATS=false` and `--no-version-check`. The selection is written once, in
`run_fixture_build.py`.

## What it covers

- The parser and the loader end to end on fixture inputs, through their command lines.
- Step 5 selects: `path:models/staging/filed`, `path:models/staging/readings`,
  `path:models/staging/stg_v05_scope.sql`, `resource_type:seed`, `path:models/intermediate/int_*.sql`,
  and four hand-written tests that read no model (`int_source_row_text_patterns`,
  `concept_release_unmatched_fixture`, `concept_rule_namespace_gaps_fixture`,
  `filed_one_filing_row_per_folder`). It excludes `path:tests/baseline_*.sql`. With cautious indirect
  selection a data test runs only when every model it reads is selected. Last local run: `PASS=173 WARN=0
  ERROR=0 TOTAL=173` (3 seeds, 17 views, 9 tables, 134 data tests, 10 unit tests).
- Step 6: all 12 unit tests (dbt build runs a unit test only when its model is built, so the two on
  `cmp_row_set` and `cmp_excluded_quarter` need this step; the int_* ones run twice) and
  `baseline_production_wrapper_changed`, whose ceiling 0 is a rule, not a measurement: the fixture's
  copy record (`fixture/wrappers/_source.json`) holds the hash of `fixture/production_wrappers/`, so the
  drift check reads a real file and finds no change.
- `tests/ci_fixture_expected_roles.sql`: the role, rule number, cash flag, published flag and scope each
  fixture context must get, the fund rule that must decide six of them, and the filing each quarter must
  select or refuse. A rule change that moves a fixture row fails CI until that list is updated.

## The fixture

All invented. Fund cik `0000000001`, namespace `http://fixturefund.example.com/`. About 45 KB.

| File | What |
|---|---|
| `fixture/raw/bdc_xbrl/1/000000000126000011.xml` and `fixture/raw/bdc_html/1/000000000126000011.html` | A 10-Q at 2026-03-31, 26 contexts, one per row-role rule (the expected role is in a comment above each). The inline document places every numeric fact. |
| `fixture/raw/bdc_xbrl/1/000000000126000012.xml` | A cover-only 10-Q/A for the same quarter: skipped by filing selection, its context superseded. |
| `fixture/raw/bdc_xbrl/1/000000000126000001.xml`, `...0002.xml` | Two 10-K originals for 2025-12-31: the quarter is refused (`two_originals_same_quarter`). |
| `fixture/wrappers/0000000001.json` | The wrapper copy: old-style declarations (rate reading, a legal-entity member, a label suffix, a cash identifier, a procedure the loader lists as not loaded, an untagged value, a relabel) and five `reading_rules` (fair value and term fact from the fund's own concepts, `subtotal_on_fair_value`, two `position_without_term_fact` with label examples, one dated with `fair_value_zero`). |
| `fixture/wrappers/_source.json`, `fixture/production_wrappers/0000000001.json` | The copy record and the production wrapper it stands beside. |
| `fixture/row_corrections.csv`, `fixture/row_corrections_by_context.csv` | One row each for the fund, and one for another fund that the loader drops. |
| `fixture/scope.json` | `findings_scope.ciks`: the one fund. |
| `fixture/output/` | Column names and types of the holdings file (the columns `stg_holdings` reads) and the header of `fund_financials.csv`. No rows. |

The fixture's bytes are hashed (the drift check, the parser's input hashes), so `.gitattributes` here
turns off line-ending conversion for it.

Why the parser and loader run in the job rather than committing their Parquet output: the inputs are
small, readable text that a reviewer can check, and a change to the parser or loader is exercised on
every run instead of leaving stale committed output to be regenerated by hand.

## What it does not cover

- Every model that reads the pipeline's `data/output/`: the step 1 staging views (other than the two
  unit-test inputs, built over empty stand-ins), the marts, `cmp_row_set` and `cmp_excluded_quarter`.
  Their unit tests run; their data tests do not.
- Every baseline test except `baseline_production_wrapper_changed`: their ceilings are measured on real
  data.
- Real filings. A fixture of 29 contexts shows the rules run and give the stated roles on invented
  rows; it says nothing about whether they are right on any fund's filings. A passing fixture build is
  not a statement that the data is correct.
- The `.ps1` wrappers (`dbt.ps1`, `parse.ps1`, `load_readings.ps1`): the script calls Python and dbt
  directly so the same command runs on Linux.

## When it fails

- A model or rule change moved a fixture row: read the failing rows of `ci_fixture_expected_roles`
  (stored in the work folder's `ci.duckdb`, schema `main_dbt_test__audit`). If the move is intended,
  change the expectation in the test and say why in the commit.
- A new `int_*` model is selected automatically. A new data test on it runs when every model it reads
  is selected.
- A new staging view that reads `data/output/` is not selected; a new model that reads one and sits in
  `models/intermediate/` under another name than `int_*` is not selected either.
