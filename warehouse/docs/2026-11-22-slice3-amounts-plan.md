# Slice 3 plan: amounts

Date: 2026-11-22. Owner confirmed the slice 2 controller rulings and the push on 2026-11-22.

> For agentic workers: use superpowers:subagent-driven-development to run this plan task by task.
> Tasks give requirements, not full code (ledger ruling, slice 2): the SQL depends on measured data.

**Goal.** For every position row of the five v0.5 funds, read fair value, cost, principal (and its
unit), shares and share of net assets from the tagged facts, convert them under rules that are data,
and compare them with production: fair value, cost and principal to the dollar.

**Architecture.** Two new dbt models under `warehouse/models/intermediate/`: `int_field_read` (the
filed value, unchanged) and `int_field_normalised` (the canonical value and the action applied), then
a comparison model `cmp_amount`. Standard concepts move from SQL literals into one seed. Fund rules
come only from `stg_reading_rule` (the wrapper copies). No correction is applied (slice 5). No rate
is read or converted (slice 4).

**Tech stack.** dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3, Python 3.13 in `warehouse\.venv`.

**Spec.** `warehouse/docs/intermediate_spine.md`, sections 4, 5, 6.3, 6.4, 7, 8 and decisions D1, D5,
D6, D7, D9, D10, D13. Read it. Where this plan and the spec disagree, the spec wins.

## Global Constraints

- Scope is the five v0.5 funds (`stg_v05_scope`). Nothing outside `warehouse/`, except one appended
  entry in `docs/agent_changelog.md` in the last task and the `warehouse` job in
  `.github/workflows/ci.yml`. Do not edit `AGENTS.md`, `pipeline/`, `data/`, `scripts/`, `tests/`
  or any production wrapper under `data/overrides/`.
- Fund rules live only in the wrapper copies `warehouse/wrappers/<cik>.json`, section
  `reading_rules` (D10). After editing a copy, run `.\warehouse\load_readings.ps1`. No fund's name,
  CIK, label or concept appears in SQL, in a seed, or in Python.
- This slice reads and converts amounts only. It does not apply a correction, read a rate, spread,
  PIK rate or maturity, or change a role. **No row of `int_source_row` or `cmp_row_set` may change**
  unless a task says so; a change is a defect to explain, not to absorb.
- A field that cannot be decided is left empty with a status and a reason (D5). It is never filled to
  make the comparison match. Do not tune a rule to one fund's rows.
- Reproduction (D1): fair value, cost and principal equal production to the dollar; every difference
  is listed with a cause from this closed list: `old_wrong`, `new_wrong`, `convention`,
  `needs_correction`, `needs_store_not_loaded`, `production_stale`, `owner_review`,
  `not_yet_explained`. A cause is evidence, not a guess: say what was checked and how many rows
  were opened.
- Agreement with production shows the two agree. It does not show either is right. Say so wherever
  a result is reported.
- Every value on a published row names the rule it was read under (spec section 7): a concept-map
  row, a fund rule, or a global default. An action not in `seeds/reading_action.csv` fails the build.
- Rule resolution (spec section 5): the most specific matching rule wins; two equally specific
  matches are an error, not a tie-break; a rule's dates are respected.
- Run dbt only through `.\warehouse\dbt.ps1` from the repository root (PowerShell). Python only
  through `warehouse\.venv\Scripts\python.exe`. Never `pip install` anywhere.
- No inline Python: no `python -`, `python -c`, heredocs or here-strings piped to Python. Put any
  diagnostic in a named file under `warehouse/scripts/slice3/` with a timeout and a row limit, and
  leave no Python process running. Query helpers exist: `warehouse/scripts/slice2/run_sql.py`,
  `run_sql_vars.py`, `export_query.py`.
- No network calls. No `git stash`. Do not revert or stage anything you did not write: the tree is
  dirty with other people's work. Stage files by path.
- Do not spawn subagents.
- ASCII only in SQL comments, logs and docs.
- dbt style follows the existing models: leading commas, one model one decision, a comment line at
  the top saying what the model decides, tests in the `.yml` next to the models, hand-written tests
  in `warehouse/tests/`. Measured conditions use a baseline test with a ceiling in `dbt_project.yml`
  (`baseline_max`), set to the measured count.
- The full build must end with `ERROR=0`. Last result before this slice:
  `PASS=319 WARN=19 ERROR=0 TOTAL=338`. Python tests: 141. CI fixture build:
  `PASS=176 WARN=0 ERROR=0`, drift step `PASS=15`.
- Commit at the end of each task, with a subject line and two to four bullets, ending with the
  attribution lines the controller gives in the dispatch.

## File map

| File | Responsibility |
|---|---|
| `seeds/concept_map.csv` (new) | The standard concepts: one row per field and concept, with the namespaces accepted. The only place a standard concept name is written |
| `models/intermediate/int_context_feature.sql` (modify) | Reads concepts from the seed instead of literals. Same output |
| `models/intermediate/int_field_read.sql` (new) | The filed value of each amount field on each position, its unit, its fact, its printed text |
| `models/intermediate/int_field_rule.sql` (new) | Which rule applies to each position and field (resolution only) |
| `models/intermediate/int_field_normalised.sql` (new) | The canonical value and the action applied |
| `models/staging/stg_fx_rate.sql` (new) | The currency rates production uses, as a view |
| `models/intermediate/cmp_amount.sql` (new) | This layer against production, per position and field, with a cause |
| `docs/baseline_amounts_2026-11-22.md` (new) | Counts, causes, what was not checked |

---

### Task 1: Parked items from slice 2, and one definition of the standard concepts

**Files:**
- Create: `warehouse/seeds/concept_map.csv`, its entry in `warehouse/seeds/_seeds.yml`
- Modify: `warehouse/models/intermediate/int_context_feature.sql`, `int_source_row.sql`,
  `cmp_row_set.sql`, `_intermediate.yml`; macros that list concepts (`macros/concept_*.sql`)
- Modify: `warehouse/models/staging/readings/` (correction-store drift), `warehouse/readings_loader/`
  only if the manifest lacks the store hashes
- Create: tests under `warehouse/tests/`; ceilings in `warehouse/dbt_project.yml`
- Modify: `warehouse/ci/README.md`

**Interfaces:**
- Consumes: the slice 2 models as they stand at `ab299286`.
- Produces:
  - `concept_map` seed: `concept_map_id`, `field` (`fair_value`, `cost`, `principal_amount`,
    `shares`, `pct_of_net_assets`, and the term facts slice 2 already reads: `rate`, `spread`,
    `pik_rate`, `maturity`, `ownership_percent`), `concept_local`, `namespace_pattern`, `note`.
  - `int_context_feature`: unchanged columns, plus `fair_value_rule_id` filled for the standard
    concept too (the `concept_map_id`), so no fair value is without a rule.
  - `int_source_row.cash_source`: `fund_rule`, `seed_pattern` or `filed_cash_axis`; not null where
    `is_cash`.

**Requirements:**
- The seven parked items, from the slice 2 ledger's last ruling
  (`.superpowers/sdd/2026-11-19-slice2-row-roles-plan/progress.md`, line 125):
  (a) `cash_source` column with a not-null-where-cash test and an accepted-values test;
  (b) the row-correction stores the loader reads are re-hashed at build time and compared with the
  hash in the loader's manifest, as the wrapper copies are (`stg_wrapper_drift`); a changed store
  fails the build until `load_readings.ps1` is run;
  (c) a baseline test with a ceiling on fund-rule releases in excluded quarters;
  (d) the `needs_correction` term branch of `cmp_row_set` excludes rows held for two scopes;
  (e) a unit case for a cash row matched by both a fund rule and a seed pattern;
  (f) a note in `ci/README.md` that `dbt test --vars` does not repoint the drift view;
  (g) the concept map (below).
- Concept map: find every place a standard concept name is written as a literal
  (`int_context_feature`, the macros, tests, any other model; the final review counted four places)
  and replace it with a read of the seed. Namespaces keep ruling 12: local name plus namespace
  pattern, never the prefix. The FASB supplement namespace stays accepted for the term facts that
  use it today. List in the report every literal removed and where.
- Find the concept for share of net assets by querying `stg_filed_fact` for the five funds; list
  the candidates with counts per fund and say which goes in the seed and why. Do not guess a name.
- **Nothing moves.** Before and after: role counts by fund, role and `role_rule`; every `cmp_row_set`
  count by fund, side and cause; the `is_cash` count. All identical. Save both as files under
  `warehouse/scripts/slice3/` and show the diff is empty in the report.
- Tests: `concept_map` key unique; each `field` in its list; a (field, concept, namespace) appears
  once; a test that fails if a model under `models/intermediate/` contains a standard concept local
  name as a literal (a grep-style check in Python under `warehouse/pytests/` is acceptable).

**Done when:** the before/after diff is empty, the seven items are each shown done, the build ends
`ERROR=0`, and the work is committed.

---

### Task 2: Field read

**Files:**
- Create: `warehouse/models/intermediate/int_field_read.sql`
- Modify: `warehouse/models/intermediate/_intermediate.yml`
- Create: `warehouse/tests/int_field_read_*.sql`, `baseline_int_field_read_*.sql`; ceilings in
  `warehouse/dbt_project.yml`

**Interfaces:**
- Consumes: `int_source_row` (rows with `role = 'position'`, published or not), `concept_map`
  (Task 1), `stg_reading_rule` (`concept_is_fair_value` fund rules), `stg_filed_fact`,
  `stg_filed_unit`, `stg_filed_fact_placement`, `stg_filed_document_row`.
- Produces: `int_field_read`, one row per `accession`, `context_id`, `field` for the five amount
  fields (`fair_value`, `cost`, `principal_amount`, `shares`, `pct_of_net_assets`), for every
  position row, present or not:
  `cik`, `report_date`, `status` (`read`, `absent`, `unresolved`), `reason`, `value_filed`
  (numeric, as filed after the tag's own scale and sign, nothing else), `unit` (the unit measure as
  filed, for example `iso4217:USD`, `iso4217:EUR`, `xbrli:shares`, `xbrli:pure`), `decimals`,
  `fact_id`, `fact_count`, `printed_text` (the text of the same fact where the filed layer placed
  it, else null), `is_nil`, `read_rule_id` (the `concept_map_id` or the fund rule's `rule_id`).

**Requirements:**
- Spec 6.3: tagged fields only. Two facts of one concept on one context with different values make
  the field `unresolved`; the same value twice is `read` with `fact_count` 2. A nil fact is `read`
  with a null value and `is_nil` true: keep it apart from `absent`.
- Where a field has more than one concept in the map (or a fund rule adds one), the standard concept
  wins and the fund rule's concept is read only where the standard one is absent, as
  `int_context_feature` does for fair value today. Fair value here must equal
  `int_context_feature.fair_value` on every position row: test it, ceiling 0.
- `value_filed` is not converted, not sign-flipped, not rescaled beyond what the tag itself states.
  Say in the model comment how the filed layer stores scale and sign (read `filed_layer.md`) so the
  reader knows what "as filed" means here.
- Tests: key unique; exactly five rows per position row; `status` in its list; `read` has a
  `fact_id` and a `read_rule_id`; `absent` has neither; every published position has fair value
  `read` (ceiling 0, or the measured count with the rows listed). Baseline tests with ceilings: the
  count of `unresolved` per field.
- Report, per fund and field: read, absent, unresolved, nil; and the units seen per field with
  counts. Flag anything unexpected (a principal in `xbrli:shares`, a cost in a foreign unit): those
  are what Task 3's rules must cover. Do not fix them here.
- This task does not read `stg_holdings`.

**Done when:** the build ends `ERROR=0`, the report gives the counts and the unit table, and the work
is committed.

---

### Task 3: Conversion

**Files:**
- Create: `warehouse/models/staging/stg_fx_rate.sql`, source entry in `models/staging/_sources.yml`
- Create: `warehouse/models/intermediate/int_field_rule.sql`, `int_field_normalised.sql`
- Modify: `warehouse/models/intermediate/_intermediate.yml`, `warehouse/seeds/role_pattern.csv` or a
  new general seed only if a global default needs a row (say which and why)
- Modify, only if a loaded rule lacks a selector the model needs: `warehouse/readings_loader/` with
  tests in `warehouse/pytests/`
- Create: `warehouse/tests/int_field_normalised_*.sql`, `baseline_int_field_*.sql`; ceilings
- Create: `warehouse/docs/owner_review_value_size_rules_2026-11-22.md`

**Interfaces:**
- Consumes: `int_field_read` (Task 2), `stg_reading_rule`, `reading_action` seed (actions marked
  slice 3: `as_filed`, `to_usd`, `reported_in_usd`, `par_tagged_as_units`, `units_tagged_as_par`,
  `bracketed_unsigned`, `cost_foreign_is_par`), the currency rate file.
- Produces:
  - `stg_fx_rate`: `currency`, `rate_date`, `usd_per_unit` (state the direction in the comment and
    test it on one known rate).
  - `int_field_rule`: one row per `accession`, `context_id`, `field`: `rule_id`, `action`,
    `parameter`, `origin`, `priority`, `candidate_count`. Resolution only, no value.
  - `int_field_normalised`: one row per `accession`, `context_id`, `field`, where `field` is now
    `fair_value`, `cost`, `principal_amount`, `principal_amount_usd`, `shares`,
    `pct_of_net_assets`: `value` (canonical), `currency` (for `principal_amount`), `value_filed`,
    `action`, `rule_id`, `status` (`normalised`, `absent`, `unresolved`), `reason`,
    `fx_rate`, `fx_rate_date` (where `to_usd` was applied).

**Requirements:**
- Currency rates: production's reference is `fred_h10` (wrapper key
  `source_encodings.principal_usd_reference`). Read `pipeline/monetary_fx.py` and
  `pipeline/source_encodings.py` to find the exact file (candidates: `data/reference/fx_rates.csv`,
  `data/reference/fx_fred/`), the rate direction, and what production does when the report date has
  no rate (prior business day, or none). Reproduce that behaviour and state it in the model comment.
  The path is a dbt variable. Do not download anything.
- Read production's conversion code before writing each action, and say in the report where the
  action's meaning was taken from (file and function). The actions' effects are in spec 6.4; the
  three not in that table (`par_tagged_as_units`, `units_tagged_as_par`, `bracketed_unsigned`,
  `cost_foreign_is_par`) are defined by the wrapper declarations they were loaded from
  (`wrapper_fit_2026-11-19.md`, `baseline_readings_2026-11-19.md`).
- Global defaults are rules too: `as_filed` for an amount in dollars is a row with
  `origin = 'global_default'`, lowest priority, not an `else` branch in SQL. A field with no
  matching rule, or an action not built in this slice, is `unresolved` with the reason; a rule
  naming an action absent from the seed fails the build.
- Two equally specific matching rules: the field is `unresolved` with reason `rule_conflict`, and a
  test with ceiling 0 fails the build. Do not pick one.
- `to_usd` with no rate for the currency or date: `unresolved`, reason `no_fx_rate`, counted with a
  ceiling. A principal already in dollars gets `principal_amount_usd` equal to `principal_amount`
  under the default rule.
- The value-size readings (`par_tagged_as_units` row modes, spec 6.4) decide from the size of a
  number. Load and apply them as they are, and list every one in
  `owner_review_value_size_rules_2026-11-22.md` with the fund, the threshold, the rows it changes
  per quarter, and three example rows. Do not change a threshold.
- Tests: key unique; every `normalised` value has a `rule_id` and an `action` in the seed; `as_filed`
  leaves the value equal to `value_filed`; `fair_value` on a published position is `normalised`
  (ceiling 0 or measured, rows listed). A dbt unit test per action on a hand-made case, each with
  one case the action must NOT touch (for example a dollar principal under a `to_usd` rule scoped to
  another unit). Baseline tests with ceilings: `unresolved` per field and reason.
- Spec section 7, the sum check: per fund and report date, the published positions' normalised fair
  value against the filed total on the published basis and on the cash basis that
  `fact_fund_period` uses (step 1). A baseline test with a ceiling on the number of fund-quarters
  that do not tie; list each with both figures. Slice 2 recorded that BCRED and HPS tie; say whether
  that still holds and report the other three.
- This task does not read `stg_holdings`.
- Report per fund and field: counts by action and by status and reason.

**Done when:** every action has a unit test, the sum check is reported for all five funds, the build
ends `ERROR=0`, and the work is committed.

---

### Task 4: Comparison of amounts with production

**Files:**
- Create: `warehouse/models/intermediate/cmp_amount.sql`
- Modify: `warehouse/models/intermediate/_intermediate.yml`, `warehouse/dbt_project.yml` (ceilings)
- Create: `warehouse/tests/baseline_cmp_amount_*.sql` (reuse `tests/generic/baseline_cmp_cause.sql`
  if it fits), `warehouse/tests/cmp_amount_key_and_cause.sql`
- Create: `warehouse/docs/baseline_amounts_2026-11-22.md`

**Interfaces:**
- Consumes: `int_field_normalised` (Task 3), `cmp_row_set` (rows with `side = 'both'`, both bases),
  `cmp_excluded_quarter`, `stg_holdings`, `stg_correction`, `stg_cost_donor_audit`.
- Produces: `cmp_amount`, one row per `accession`, `context_id`, `field` for rows on both sides:
  `cik`, `report_date`, `is_published`, `value_new`, `value_production`, `difference`,
  `outcome` (`equal`, `differs`, `new_empty`, `production_empty`, `both_empty`), `cause` (null where
  `equal` or `both_empty`), `cause_detail`.

**Requirements:**
- Join to production on `accession_number` and `src_context_id`, as `cmp_row_set` does. Quarters in
  `cmp_excluded_quarter` stay out.
- Field pairs: fair value to `fair_value`; principal to `principal_amount`, its currency to
  `principal_amount_currency`, and `principal_amount_usd` to `principal_amount_usd`; shares to
  `shares_held`; share of net assets to `pct_of_net_assets`. Cost: production has `cost` and
  `cost_reported`; read how they differ (`stg_cost_donor_audit`, the pipeline code that fills
  `cost`) and compare against the one that holds the filed cost. Say which and why; report the other
  as a second measure.
- D1: fair value, cost and principal are equal when they agree to the dollar (absolute difference
  under 1). Shares and share of net assets are reported as measured differences; state the tolerance
  used and why.
- Every `differs`, `new_empty` and `production_empty` row gets a cause through a rule on row
  features, never a list of ids. Expected sources of difference, each to be confirmed against the
  data, not assumed: a correction production applied (`stg_holdings.corrected_fields`,
  `stg_correction`) is `needs_correction`; a cost production filled from a donor row is
  `convention` or `needs_store_not_loaded` (decide from the code and say why); a store slice 1 did
  not load is `needs_store_not_loaded`. Open the filing rows for a sample of each group before
  naming a cause, and say how many were opened.
- If a group shows a defect in Task 2 or Task 3 (`new_wrong`), do not patch it here: list it with
  the rows and the fix. The controller decides.
- Baseline tests with ceilings: one per basis, field and cause for fair value, cost and principal;
  one per field for `not_yet_explained` on shares and share of net assets. Each set to the measured
  count.
- `baseline_amounts_2026-11-22.md`: per fund and field, the counts by outcome; the causes with
  counts, fair value affected and evidence; the Task 2 and Task 3 unresolved counts; the sum check;
  what was not checked. Plain language, short sentences, tables for numbers. It states that
  agreement is not correctness, and names what this comparison cannot see: a value both pipelines
  read wrongly in the same way.
- Three open owner items are examined here and reported as evidence, not decided:
  (1) HPS JV commitment lines: what the filed fair value is beside the commitment, on the printed
  rows of two quarters;
  (2) the two Apollo rollups with a cost gap above 10 pct (Chemicals Heubach, Media Material+): the
  printed rows beneath each, and whether an untagged position sits there;
  (3) the 46 holdings rows whose fair value matches no filed fact on their context (Apollo 44,
  Ares 2; `HANDOFF.md`, "Not examined"): whether they are the same rows as a cause group here.

**Done when:** every differing row has a cause, the baseline file is written, the three owner items
have their evidence, the build ends `ERROR=0`, and the work is committed.

---

### Task 5: CI fixture, and records

**Files:**
- Modify: `warehouse/ci/` (fixture, `run_fixture_build.py`, `README.md`, the expected-values test)
- Modify: `.github/workflows/ci.yml` only if the job's commands change
- Modify: `warehouse/README.md`, `warehouse/docs/HANDOFF.md`, `warehouse/docs/intermediate_spine.md`
  (status line and the "path to confirm" cell in section 4 only)
- Modify: `docs/agent_changelog.md` (append one entry at the end; touch nothing else in it)

**Interfaces:**
- Consumes: the models of Tasks 1 to 4.

**Requirements:**
- The CI fixture build covers `concept_map`, `int_field_read`, `int_field_rule` and
  `int_field_normalised`, with a small committed currency-rate fixture and at least one fixture
  position that takes a non-default action. `cmp_amount` is left out, as `cmp_row_set` is. Add an
  expected-values test like `ci_fixture_expected_roles.sql` for the fixture's amounts.
- Check the result of the first GitHub run of the `warehouse` job (pushed 2026-11-22, run
  45015590307) with `gh run view`. If it failed, the fix is part of this task: report the log lines
  and the change. The other two CI jobs are not this task's concern; report their state only.
- Prove the fixture commands locally in an empty folder before changing the workflow.
- `README.md`: a short section on reading and converting a field, in the plain style of the
  existing sections, explaining seed, rule resolution and the comparison in dbt terms a newcomer
  can follow (the owner is learning dbt).
- `HANDOFF.md`: a dated section with the state after slice 3, the counts, the open owner decisions,
  the rulings made without the owner (each with its cost if wrong), and what slice 4 (rates) is.
- Changelog entry: what was added, the counts, the build result, and the sentence that a passing
  build and agreement with production are not statements that the data is correct.

**Done when:** the local proof of the CI commands is in the report, the CI run's result is stated,
the build ends `ERROR=0`, and the work is committed.

---

## Self-review (2026-11-22)

- Spec coverage: 6.3 (Task 2), 6.4 amount actions (Task 3), section 5 rule use (Task 3), section 7
  checks that apply to amounts: keys, every value names a rule, sum to filed total, unresolved
  ceilings (Tasks 2 to 3), section 8 (Task 4). Not in this slice, by the spec's order of work:
  rates and the cash-plus-PIK check (slice 4), corrections and "a correction that did not apply"
  (slice 5), `int_observation` and `int_reading_finding` (slice 6). The findings "printed number
  against tagged number" and "concept set changed against the prior quarter" are left for slice 6
  with the findings model; `printed_text` is carried in Task 2 so the first needs no re-read.
- Open point from spec section 11, "which correction stores hold entries for the five funds": the
  loader of slice 1 already reads the wrappers' row-level entries and two row-correction files;
  Task 1 (b) hashes those. A full list of stores is owed in the slice 5 plan.
- Names are consistent across tasks: `int_field_read`, `int_field_rule`, `int_field_normalised`,
  `cmp_amount`, `concept_map`, `stg_fx_rate`, `cash_source`.
