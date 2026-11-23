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
| 6 | `dbt run --empty --select cmp_row_set cmp_excluded_quarter` | same |
| 7 | `dbt test --select test_type:unit path:tests/baseline_production_wrapper_changed.sql path:tests/baseline_wrapper_copy_changed_since_load.sql path:tests/baseline_row_store_changed_since_load.sql` | same |

Step 6 (slice 3): `--empty` makes dbt build the two comparison models with no rows. They read the
pipeline's `data/output/`, which CI does not have, so their data cannot be built here. The unit test
of `cmp_amount` (`cmp_amount_cause_rules`), and since slice 4 that of `cmp_rate` (`cmp_rate_cause_rules`),
need them to exist so they can read their column types; the empty build gives them that. No data test
of theirs runs. `cmp_amount` and `cmp_rate` themselves are not built in CI.

dbt runs on its own profile target, `ci` (`warehouse/profiles.yml`), whose database file is set by the
script (`WAREHOUSE_CI_DUCKDB`); it never touches `target/warehouse.duckdb`. Every path reaches dbt through
`--vars` (`filed_dir`, `readings_dir`, `thresholds_file`, `output_dir`, `wrappers_dir`,
`production_wrappers_dir`, `row_store_files`, `fx_rate_file`); no model is edited. The script
also passes `ci_fixture: true`, which switches on `tests/ci_fixture_expected_roles.sql`,
`tests/ci_fixture_expected_amounts.sql` and `tests/ci_fixture_expected_rates.sql`, and sets
`DBT_SEND_ANONYMOUS_USAGE_STATS=false` and `--no-version-check`. The selection is written once, in
`run_fixture_build.py`.

## What it covers

- The parser and the loader end to end on fixture inputs, through their command lines.
- Step 5 selects: `path:models/staging/filed`, `path:models/staging/readings`,
  `path:models/staging/stg_v05_scope.sql`, `path:models/staging/stg_fx_rate.sql`, `resource_type:seed`,
  `path:models/intermediate/int_*.sql`, and four hand-written tests that read no model
  (`int_source_row_text_patterns`, `concept_release_unmatched_fixture`,
  `concept_rule_namespace_gaps_fixture`, `filed_one_filing_row_per_folder`). It excludes
  `path:tests/baseline_*.sql`. With cautious indirect selection a data test runs only when every model
  it reads is selected. Since slice 3 this includes the amounts: the seeds `concept_map`,
  `field_rule_default` and `action_field`, the view `stg_fx_rate` (over the fixture's rate file), and
  the tables `int_field_read`, `int_field_rule` and `int_field_normalised`. `cmp_amount` is left out,
  as `cmp_row_set` is: it reads production's holdings; `cmp_rate` likewise (slice 4). Last local run
  (rate rulings fix round 1, 2026-11-23): `PASS=334 WARN=5 ERROR=0 TOTAL=339`; the new models `int_rate_scale` and
  `int_rate_tag_cell` and their tests are selected as `int_*` (slice 4 Task 5: 318). The 5 warnings are the generic unresolved baselines on the fixture's
  deliberate unresolved rate rows (see below). Slice 3 ended at 281.
- Step 6: `PASS=2` (the two empty comparison models).
- Step 7: all 32 unit tests (dbt build runs a unit test only when its model is built, so the five on
  `cmp_row_set`, `cmp_excluded_quarter`, `cmp_amount` and `cmp_rate` need this step; the int_* ones run twice) and
  the three drift baselines, whose ceilings 0 are rules, not measurements. All hash the files at build
  time (`stg_wrapper_drift`, `stg_row_store_drift`). `baseline_production_wrapper_changed`: the fixture's copy record
  (`fixture/wrappers/_source.json`) holds the hash of `fixture/production_wrappers/`, so the check reads
  a real file and finds no change. `baseline_wrapper_copy_changed_since_load`: the fixture's wrapper copy
  against the hash the loader recorded in step 2. `baseline_row_store_changed_since_load` (slice 3): the
  fixture's two row stores against the hashes the loader recorded in step 2 (`stg_row_store_drift`).
  Since slice 4 the two wrapper checks hash the text with CRLF read as LF. Last local run (rate rulings
  fix round 1, 2026-11-23): `PASS=35 TOTAL=35` (32 unit tests, 3 drift baselines; slice 4 Task 5: 33).

### The drift views and `dbt test --vars`

The three drift checks read views (`stg_wrapper_drift`, `stg_row_store_drift`) whose file paths are
written into the view when it is built. `dbt test --vars "{wrappers_dir: ...}"` alone does NOT repoint
them: the test reads the view as last built, with the old paths, and can pass on files it never read. To
check other files, rebuild the view with the same vars first (`dbt build --select stg_wrapper_drift
--vars ...`, or `stg_row_store_drift`). This script builds the views in step 5 with its vars before
step 7 tests them, and a full `dbt.ps1 build` rebuilds them with the project's vars.

### The three expected-values tests

- `tests/ci_fixture_expected_roles.sql`: the role, rule number, cash flag, published flag and scope each
  fixture context must get, the fund rule that must decide six of them, and the filing each quarter must
  select or refuse. A rule change that moves a fixture row fails CI until that list is updated.
- `tests/ci_fixture_expected_amounts.sql` (slice 3): for each fixture position, every amount field that
  is not absent (35 of 108), with its value, currency, action, the rule that converted it and the rule it
  was read under. Every other field must be absent with reason `no_fact`, and every position must have
  its six amount rows. Three rows take something other than the plain dollar default on purpose: c-7's
  principal is in euros, so its dollar value takes the fund rule `to_usd` at the 2026-03-27 rate (four
  days before the report date); c-3's share of net assets 0.1 becomes 10.0 (`fraction_to_percent`);
  c-17's fair value is read under the fund rule `concept_is_fair_value`. Shown to bite: with c-7's
  expected dollar value changed from 194.4 to 194.5, step 5 ends `FAIL 1 ci_fixture_expected_amounts`.
- `tests/ci_fixture_expected_rates.sql` (slice 4): for each fixture position, every rate field
  (`interest_rate`, `interest_rate_cash`, `pik_rate`, `spread`, `maturity_date`) that is not absent with
  reason `no_fact` (17 of 90: 18 positions), with its status, reason, value or date, `rate_kind`, action and the rule
  that converted it. Every position must have its five rate rows. The fund reads its rate tag as all-in
  and declares a PIK-only coupon reading. The rows are there on purpose:

  | Position | What it shows | Expected |
  |---|---|---|
  | c-3 | a rate tag and a PIK tag | all-in 9.0 (`all_in`), cash leg 7.0, PIK 2.0; the legs check (`int_field_normalised_rate_legs`) runs on this row |
  | c-7 | a rate tag and a spread | all-in 8.0; spread 5.0 (default `fraction_to_percent`); cash leg empty, `no_pik_read` |
  | c-24 | a rate tag only | all-in 7.0; cash leg empty, `no_pik_read` |
  | c-17 | only a PIK tag (12.50 printed) | all-in rate, cash leg and spread unresolved `text_not_read`, kind `unresolved`; PIK rate 12.5 still read |
  | c-25 | a rate tag filed as 7.00 (a percent) in a ratio unit | all-in rate and cash leg unresolved `scale_not_decided`, no value |
  | c-8 | a rate tag in the unit written `xbrli:pure` | unresolved `unit_not_pure`: unit kinds are read from the unit text, which knows `pure` and `utr:Rate` only. Pins today's behaviour; none of the five funds writes the prefix |
  | c-4 | a maturity date | 2030-01-01, `as_filed` (`gd_maturity_date`) |

  Shown to bite: with c-3's expected cash leg changed from 7.0 to 7.1, step 5 ends
  `FAIL 1 ci_fixture_expected_rates`.

The generic baselines on unresolved fields (`baseline_int_field_normalised_unresolved_*`, declared in
`_intermediate.yml`, not files under `tests/baseline_*`) are selected in step 5. Their ceilings are
measured on real data, so here they only warn: on the fixture's deliberate unresolved rows (c-17,
c-25) five of them warn.

## The fixture

All invented. Fund cik `0000000001`, namespace `http://fixturefund.example.com/`. 14 files, about 41 KB.

| File | What |
|---|---|
| `fixture/raw/bdc_xbrl/1/000000000126000011.xml` and `fixture/raw/bdc_html/1/000000000126000011.html` | A 10-Q at 2026-03-31, 26 contexts, one per row-role rule (the expected role is in a comment above each). The inline document places every numeric fact. Since slice 3 it also has a principal in euros (c-7) and a share of net assets written in the unit `pure` without a prefix, as the five funds write it (c-3). Since slice 4: PIK rates on c-3 and c-17, a spread on c-7, c-25's rate filed as a percent; the rate facts are in the unprefixed `pure` unit except c-8's (see the rates test). |
| `fixture/fx_rates.csv` | Three US-dollar-per-unit quotes in the columns of the rate file production uses: two from 2018-10-01 and EUR on 2026-03-27 for c-7. |
| `fixture/raw/bdc_xbrl/1/000000000126000012.xml` | A cover-only 10-Q/A for the same quarter: skipped by filing selection, its context superseded. |
| `fixture/raw/bdc_xbrl/1/000000000126000001.xml`, `...0002.xml` | Two 10-K originals for 2025-12-31: the quarter is refused (`two_originals_same_quarter`). |
| `fixture/wrappers/0000000001.json` | The wrapper copy: old-style declarations (rate reading, dollar principal by `fred_h10` (slice 3), a legal-entity member, a label suffix, a cash identifier, a procedure the loader lists as not loaded, an untagged value, a relabel) and five `reading_rules` (fair value and term fact from the fund's own concepts, `subtotal_on_fair_value`, two `position_without_term_fact` with label examples, one dated with `fair_value_zero`). Since slice 4 also `pik_only_tag_reading: coupon`, in the copy only (not in the production stand-in). |
| `fixture/wrappers/_source.json`, `fixture/production_wrappers/0000000001.json` | The copy record and the production wrapper it stands beside. |
| `fixture/row_corrections.csv`, `fixture/row_corrections_by_context.csv` | One row each for the fund, and one for another fund that the loader drops. |
| `fixture/scope.json` | `findings_scope.ciks`: the one fund. |
| `fixture/output/` | Column names and types of the holdings file (the columns `stg_holdings` reads) and the header of `fund_financials.csv`. No rows. |

The fixture's bytes are hashed (the drift check, the parser's input hashes), so `.gitattributes` here
turns off line-ending conversion for it.

`warehouse/pytests/fixtures/` was not used: its two files (`mini_inline.html`, `mini_instance.xml`) hold
no investment contexts and cannot reach the role rules.

Why the parser and loader run in the job rather than committing their Parquet output: the inputs are
small, readable text that a reviewer can check, and a change to the parser or loader is exercised on
every run instead of leaving stale committed output to be regenerated by hand.

## What it does not cover

- Every model that reads the pipeline's `data/output/`: the step 1 staging views (other than the
  unit-test inputs, built over empty stand-ins), the marts, `cmp_row_set`, `cmp_excluded_quarter`,
  `cmp_amount` and `cmp_rate`. Their unit tests run; their data tests do not.
- The amount actions the fixture does not use (`reported_in_usd`, `cost_foreign_is_par`,
  `par_tagged_as_units`, `units_tagged_as_par`, `bracketed_unsigned`, `concept_is_cost`) and the rate
  actions it does not reach (`rate_is_cash_leg`, `pik_only_is_margin`, `printed_margin_cash_plus_pik`,
  and the coupon arithmetic of `pik_only_is_coupon`, switched off by `unread_input`): they are covered
  by unit tests only, which run in step 7.
- Every baseline test except the three drift ones (two wrapper, one row store): their ceilings are
  measured on real data. The generic unresolved-field baselines run in step 5 but only warn here.
- Real filings. A fixture of 29 contexts (26 in the 10-Q, one in each of the other three filings, as
  in the table below) shows the rules run and give the stated roles on invented
  rows, and that the amounts come out as stated; it says nothing about whether they are right on any
  fund's filings. A passing fixture build is not a statement that the data is correct.
- The `.ps1` wrappers (`dbt.ps1`, `parse.ps1`, `load_readings.ps1`): the script calls Python and dbt
  directly so the same command runs on Linux.

## When it fails

- A model or rule change moved a fixture row, amount or rate: read the failing rows of
  `ci_fixture_expected_roles`, `ci_fixture_expected_amounts` or `ci_fixture_expected_rates` (stored in the work folder's
  `ci.duckdb`, schema `main_dbt_test__audit`). If the move is intended, change the expectation in the
  test and say why in the commit.
- A new `int_*` model is selected automatically. A new data test on it runs when every model it reads
  is selected.
- A new staging view that reads `data/output/` is not selected; a new model that reads one and sits in
  `models/intermediate/` under another name than `int_*` is not selected either.
