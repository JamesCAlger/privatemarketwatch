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
- **Seed**: a small CSV kept in the project and loaded as a table. Ours are in `seeds/` (for example `manager_brand.csv`, `concept_map.csv`, `reading_action.csv`).
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
`stg_reading_rule`, `stg_correction`, `stg_reading_not_loaded`, `stg_wrapper_drift`, `stg_row_store_drift`). Spec:
`docs/intermediate_spine.md`. Since loader version 6 (slice 5 Task 2) it also reads production's two agent stores,
`data/overrides/agent_b2_corrections` and `agent_investigate_rules` (`readings_loader/agent_stores.py`): their value
entries become corrections (`stg_correction` kinds `value` keyed by a production `row_id`, and `add_row`), their
row-removing rules become rows of `stg_correction_rule`, which no model applies. Seed `correction_field` maps each
correction field, by store, to this layer's field and the step it acts at. Inventory:
`docs/baseline_corrections_2026-11-24.md` section 1.

**Where fund rules are edited.** Owner decision 2026-11-19: the new pipeline keeps its own copy of each v0.5
fund's wrapper in `warehouse/wrappers/`, taken byte for byte from production's `data/overrides/bdc_xbrl_wrappers/`
(hashes in `warehouse/wrappers/_source.json`). From now on the new pipeline's fund rules are edited there: the
old-style `source_encodings` declarations, and the new-style top-level `reading_rules` list (objects with
`target`, `action`, `parameter`, selectors `concept_namespace` (a glob on the filer's own domain) with
`concept_local`, `accession`, `axis`, `member`, `label`, `feature`, optional `valid_from` / `valid_to`, and
`evidence`). Production keeps reading its own wrappers until cutover. A change made to a production wrapper is
not seen here and must be carried into the copy by hand. dbt hashes the wrapper files at build time
(`stg_wrapper_drift`, paths from the vars `wrappers_dir` and `production_wrappers_dir`; since slice 4
the hash is of the text with CRLF line endings read as LF, so line endings alone are not a change):
`baseline_production_wrapper_changed` (ceiling 0) fails the build until the copy is brought up to date and
`_source.json` updated, and `baseline_wrapper_copy_changed_since_load` (ceiling 0) fails it when a copy was
edited after the last load (run `load_readings.ps1` again). The two row-correction stores are checked the same
way (`stg_row_store_drift`, var `row_store_files`): `baseline_row_store_changed_since_load` (ceiling 0) fails the
build when a store changed after the last load. The agent stores likewise (`stg_agent_store_drift`, var
`agent_store_dirs`): every file of a scope fund, loaded or skipped, is text-hashed; `baseline_agent_store_changed_since_load`
(ceiling 0) fails the build on a file edited, added, removed or retired after the last load.

**Standard concepts.** The XBRL concepts every filer uses (fair value, cost, principal, shares, share of net
assets, rate, spread, PIK rate, maturity, ownership percent) are defined once, in `seeds/concept_map.csv`: local
name plus namespace pattern, never the prefix. Models read the seed; `pytests/test_no_concept_literals.py` fails
if a SQL file writes one of those names. A filer's own concept is a fund rule in its wrapper copy.

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

## Amounts: reading and converting a field (slice 3)

For every position row, five amounts are read from the tagged facts: fair value, cost, principal (and
its currency), shares, and share of net assets. A sixth, the principal in US dollars, is worked out
from the principal. Spec: `docs/intermediate_spine.md` sections 5 and 6.3 to 6.4. Counts and the
comparison with production: `docs/baseline_amounts_2026-11-22.md`.

Three models, one decision each, built in this order (dbt works the order out from `ref()`):

| Model | What it decides | One row per |
|---|---|---|
| `int_field_read` | Which filed fact is the field's value, unchanged: the number as tagged, its unit, the printed text | position row and field (five) |
| `int_field_rule` | Which rule converts the field | position row and field (six) |
| `int_field_normalised` | The value after that rule's action, with the filed value beside it | position row and field (six) |

**Reading uses a seed.** `seeds/concept_map.csv` says which standard XBRL concept holds each field
(local name and namespace pattern). A seed is a small CSV that dbt loads as a table, so changing it is
a data edit, not a code edit. A filer that uses its own concept gets a fund rule in its wrapper copy
(`concept_is_fair_value`, `concept_is_cost`). Two different numbers for one field on one row make the
field `unresolved`; nothing is picked.

**Each value names the rule that decided it.** Rules come from two places, and both are rows:

- global defaults, the seed `seeds/field_rule_default.csv` (priority 10). Example: a fair value tagged
  in US dollars is taken as filed (`as_filed`); a share of net assets tagged as a fraction is turned
  into a percent (`fraction_to_percent`);
- fund rules in the wrapper copies (priority 20, or 30 when they name a filing or a row feature).
  Example: `principal_usd_reference` makes a foreign principal's dollar value `to_usd` at the report
  date's currency rate. `seeds/action_field.csv` says which fields each action acts on, and on which rows.

**Rule resolution** (`int_field_rule`): every rule that matches the row is a candidate. The highest
priority wins. At equal priority a rule that names a filing beats one that names only a row feature.
Two rules still equal are an error: the field is left empty with reason `rule_conflict`, and a
ceiling-0 test fails the build. A rule that needs a row feature the row lacks makes the field
`feature_missing`, never "no match". The action must be in `seeds/reading_action.csv` and built for
that field, or the field is `action_not_built`.

**Currency rates** come from `data/reference/monetary_conversion/fred_h10_usd_per_unit.csv` (var
`fx_rate_file`, view `stg_fx_rate`), the file behind production's rates. A quote more than 7 days
before the report date is not used: the dollar principal stays empty (`no_fx_rate`). The file was
refreshed on 2026-11-23 and now ends 2026-11-13.

**The comparison with production** (`cmp_amount`): this layer's amounts against production's, on the
rows both sides have (`cmp_row_set`), joined on filing and context. Fair value, cost and principal must
agree to the dollar (owner decision D1). Every difference gets a cause from a closed list, set by a rule
on row features, and each cause count has a ceiling per field in `dbt_project.yml` (`cmp_amount_max`).
Agreement shows the two pipelines agree. It does not show either is right: a value both read wrongly
in the same way counts as equal.

Every field that is empty for a reason is counted by a baseline test with a ceiling (for example 130
dollar principals with no currency rate). A passing build means the counts did not grow, not that the
values are correct.

## Rates: reading and converting a rate (slice 4)

For every position row, the same three models also read the rate tags, the PIK rate, the spread and
the maturity date, and convert them. Counts and the comparison with production:
`docs/baseline_rates_2026-11-23.md`. Open questions for the owner:
`docs/owner_review_rate_readings_2026-11-23.md`.

**Three stored rates** (production's contract, kept here):

| Field | What it is |
|---|---|
| `interest_rate` | The all-in rate, in percent: what the loan pays in total, cash and PIK together |
| `interest_rate_cash` | The cash leg: the part paid in cash |
| `pik_rate` | The PIK leg: the part paid in kind (added to the loan, not paid in cash) |

Beside them: `spread` (the margin over the reference rate, in percent), `maturity_date`, and
`rate_kind` on the `interest_rate` row (`all_in`, `cash` or `unresolved`: how the rate tag was read).
Where all three rates are set, a test checks that cash plus PIK equals all-in.

**How a tag becomes a rate.** Filers tag rates as fractions (0.095 for 9.5%). The default rule turns a
fraction into a percent (`fraction_to_percent`, times 100). Which leg the filer's rate tag holds is a
fund rule in its wrapper copy: `rate_is_all_in` (the tag is the all-in rate; cash = all-in less PIK) or
`rate_is_cash_leg` (the tag is the cash leg). Under `rate_is_all_in`, a row with no PIK rate read gets
cash = all-in (owner ruling, 2026-11-23; reason `cash_equals_all_in`). Production leaves that cash leg
empty. The risk: if a loan pays some PIK but the filer did not tag it, the cash leg is too high.
Where the page itself says so, the cash leg is not stored: if the rate's own printed cell contains
the word PIK on its own (for example "6.00% PIK" or "11.62% (4.50% PIK)"; not "Pikes" or "SPIKE"),
the cash leg is unresolved, reason `pik_printed_not_tagged` (controller ruling, 2026-11-23; model
`int_rate_tag_cell`). A rule is a row of data, not code: the global defaults are
rows of `seeds/field_rule_default.csv`, and `seeds/action_field.csv` says which fields and rows each
fund-rule action acts on.

**Unresolved** means the layer could not decide the value from what it reads, so the field is empty
and the reason says why. Each reason has a ceiling (a baseline test). The main ones:

| Reason | Meaning |
|---|---|
| `scale_not_decided` | A rate tagged above 1 in a ratio unit (for example 7.0): it may already be a percent. The layer does not guess from the size of the number. A fund scale rule can settle it (below) |
| `text_not_read` | The rule needs printed text the warehouse does not read yet: the printed total margin, or (for a row with only a PIK tag) the printed rate type and the loan class. `action_field.unread_input` names the missing input |
| `values_differ` | Two different numbers filed for one field on one row |
| `unit_not_pure` | A rate in a unit that is not a ratio |

**Scale rules (owner ruling, 2026-11-23).** Some filers tag a rate as a percent (13.00) where the
standard is a fraction (0.13). The layer does not decide this from the size of the number. Instead
the fund's wrapper copy holds a dated rule per filing and field: action `ratio_value_is_percent`,
with the filing's accession, the field and how the page prints it (`percent`, or `basis_points` for
a spread printed as "S+450"). The rule carries its evidence and author. It applies row by row, only
where that row's printed number agrees (model `int_rate_scale`). A row whose print disagrees stays
`scale_not_decided`. Three tests keep this honest: every decided row is re-checked against the
printed page, a rule that decides no row fails, and no stored rate may rest on an undecided number.

What the print check proves, and what it does not. In inline XBRL the tagged number is computed from
the displayed text, so "the printed number equals the tag" is close to automatic. The parts that
tell a percent from a fraction are the percent sign after the number, and the reference rate plus
"+" before a basis-point margin. The evidence test catches a logic error in `int_rate_scale` and a
filing that stops fitting its rule. It cannot catch a wrong rule (a rule on the wrong field, or a
page that prints a wrong rate). Every number above 1 in the ruled filings agreed, so today the
row-by-row gate only protects against future filings or changes. A rate tag that holds a margin
("S+610" tagged as the interest rate) is a wrong-field problem, not a scale problem: it gets no scale
rule.

**A missing rate is not "no rate".** Empty means this layer could not read a rate, not that the
position pays none. For example a row with only a PIK tag has a printed coupon, but its all-in rate is
empty until the printed text is read. One fund (Blue Owl) tags no interest rate at all.

**The comparison with production** (`cmp_rate`): the same rows and join as `cmp_amount`. Rates agree
within 1e-9 percentage points. Every difference gets a cause, and each cause (and each detail of
`needs_store_not_loaded`) has a ceiling. Agreement shows the two pipelines agree. It does not show
either is right: a rate both read wrongly in the same way counts as equal, and a rate missing on both
sides counts as `both_empty`.

A passing build means the counts did not grow and the checks hold. It is not a statement that the data
is correct.

CI runs a build on an invented fund, without the repository's data: `ci/README.md`.

## Corrections: applying them to amounts and to the row set (slice 5 Task 3)

The readings loader loads production's corrections (`stg_correction`). Slice 5 applies them on top of the
normalised values, never in place: each corrected value sits beside the filed and the normalised value,
and names the correction that set it. Spec: `docs/intermediate_spine.md` section 6.5. Counts:
`docs/baseline_corrections_2026-11-24.md` section 2.

| Model | What it decides | One row per |
|---|---|---|
| `int_correction_target` | Which row each correction acts on (a context id, a production row id, identifier text, or the production bridge) | correction and target |
| `int_correction_fair_value_cell` | What the printed fair-value cell shows, for a fair value a correction supplies on a row with no fair-value fact | such row |
| `int_correction_screen` | The outcomes that need no value (deferred field, refused key, wrong type, conflict, printed cell) | correction and target |
| `int_row_corrected` | The position set after corrections: every position, plus rows a correction makes positions | position row |
| `int_field_reread` | The conversion chain run again on those rows, before and after the corrections at step `filed` | run, row and field |
| `int_correction_application` | The outcome of each correction: applied, no_op, rejected, failed, deferred, with a reason | correction and target |
| `int_field_corrected` | The corrected value of every field, beside the filed and normalised values | position row and field (eleven) |

**The macros behind the chain.** The bodies of `int_field_read`, `int_field_rule`, `int_amount_normalised`,
`int_rate_scale`, `int_rate_tag_cell` and `int_rate_normalised` live in macros of the same names (a macro is
a reusable piece of SQL with inputs). Each model calls its macro on its usual inputs; `int_field_reread`
calls the same macros on the few rows corrections touch, so both runs follow one set of rules.

**Rates are not corrected yet.** A correction of a rate, PIK rate, spread, rate kind or maturity is
`deferred` (`rate_reading_not_rerun`) until slice 5 Task 4 re-runs the rate reading on corrected inputs.

**The production bridge is a debt.** 67 corrections keyed by identifier text find no position here by
that text; they find their row through production's holdings file. They must be re-keyed by context
before this layer can replace production.

Agreement with production is not correctness: applying production's corrections makes the two
pipelines agree; no check here sees a wrong correction.

## Where this work lives (since 2026-11-23)

The warehouse work moved from branch `ensemble-fp-experiment` in the main checkout to branch
`warehouse-dbt`, in the git worktree `.claude/worktrees/warehouse-dbt` (owner decision 2026-11-23,
cut at e44f990c). Four folders in that worktree are junctions (links) to the main checkout, shared
inputs that are not copied: `warehouse\.venv`, `warehouse\data\filed`, `data\output` and
`.superpowers`. Remove them with `rmdir` (not a recursive delete) before removing the worktree.

Two operating notes:

1. A fresh Windows checkout can write wrapper files with CRLF line endings. Since slice 4 the
   wrapper-drift check hashes the text with CRLF read as LF, so this no longer raises a false
   "production wrapper changed". After pulling this change into an existing checkout, run
   `.\warehouse\load_readings.ps1` once (the recorded hashes changed format).
2. A seed that gains a column needs `.\warehouse\dbt.ps1 seed --full-refresh --select <seed>` once in an
   existing database. A new database needs nothing.
