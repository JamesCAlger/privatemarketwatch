# Slice 4 plan: rates

Date: 2026-11-23. The owner confirmed all 18 slice 3 rulings and asked for this plan on 2026-11-23.
Status: written for the owner's review. Not started.

> For agentic workers: use superpowers:subagent-driven-development to run this plan task by task.
> Tasks give requirements, not full code (ledger ruling, slice 2): the SQL depends on measured data.
> Subagents run on Sonnet or Opus, never Fable (owner, 2026-11-12).

**Goal.** For every position row of the five v0.5 funds, read the interest rate, the cash-pay rate,
the PIK rate, the spread and the maturity date from the tagged facts, convert them under rules that
are data, and compare them with production as measured differences with causes.

**Architecture.** No new pipeline stage. `int_field_read`, `int_field_rule` and
`int_field_normalised` (slice 3) are extended from amounts to rate fields and one date field. A new
comparison model `cmp_rate` sits beside `cmp_amount`. Fund rules come only from `stg_reading_rule`
(the wrapper copies). No correction is applied (slice 5). No rate is derived from base rate plus
spread (spec section 10: after reproduction only).

**Tech stack.** dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3, Python 3.13 in `warehouse\.venv`.

**Spec.** `warehouse/docs/intermediate_spine.md`, sections 5, 6.3, 6.4, 7, 8, 10 (what NOT to build)
and decisions D1, D5, D6, D10, D16, D17. Read it. Where this plan and the spec disagree, the spec
wins. Also read the `interest_rate` bullet under "Non-Negotiable Data Semantics" in `AGENTS.md`.

## Global Constraints

- Scope is the five v0.5 funds (`stg_v05_scope`). Nothing outside `warehouse/`, except one appended
  entry in `docs/agent_changelog.md` in the last task. Do not edit `AGENTS.md`, `pipeline/`, `data/`,
  `scripts/`, `tests/` or any production wrapper under `data/overrides/`.
- Fund rules live only in the wrapper copies `warehouse/wrappers/<cik>.json`, section
  `reading_rules` (D10). After editing a copy, run `.\warehouse\load_readings.ps1`. No fund's name,
  CIK, label or concept appears in SQL, in a seed, or in Python.
- This slice reads and converts rates, the spread and the maturity date only. It does not apply a
  correction, change a role, or change an amount. **No row of `int_source_row`, `cmp_row_set` or
  `cmp_amount`, and no amount-field row of `int_field_read`, `int_field_rule` or
  `int_field_normalised`, may change** unless a task says so. A change is a defect to explain, not
  to absorb. Each task proves it with row snapshots before and after, as slice 3 did
  (`scripts/slice3/q_fw_snap_*.sql` are the pattern).
- Stored meaning of the rate fields (production's contract, 2026-10-06; `AGENTS.md`):
  `interest_rate` is the all-in rate, `interest_rate_cash` the cash leg, `pik_rate` the PIK leg,
  `interest_rate_kind` says how the tag was read (`all_in`, `cash`, `unresolved`). A row with no
  supported reading stays `unresolved` with no rate. Do not fill a rate to make the comparison
  match. A missing rate is not evidence that the position has none.
- A field that cannot be decided is left empty with a status and a reason (D5). Do not tune a rule
  to one fund's rows.
- Reproduction (D1): rates are "other fields": differences are counted per fund and field, each
  group with a cause from the closed list `old_wrong`, `new_wrong`, `convention`,
  `needs_correction`, `needs_store_not_loaded`, `production_stale`, `owner_review`,
  `not_yet_explained`. A cause is evidence, not a guess: say what was checked and how many rows
  were opened.
- Agreement with production shows the two agree. It does not show either is right. No check here
  detects a wrong rate that both pipelines read the same way. Say so wherever a result is reported.
- Every value on a published row names the rule it was read under (spec section 7). An action not in
  `seeds/reading_action.csv` fails the build.
- Rule resolution (spec section 5, confirmed by the owner 2026-11-23): higher priority wins; at
  equal priority a rule naming a filing beats a rule naming a row feature; two still equal are a
  conflict (`rule_conflict`, ceiling 0). A missing row feature is an error. A rule's dates are
  respected.
- Run dbt only through `.\warehouse\dbt.ps1` from the repository root (PowerShell). Python only
  through `warehouse\.venv\Scripts\python.exe`. Never `pip install` anywhere.
- No inline Python: no `python -`, `python -c`, heredocs or here-strings piped to Python. Put any
  diagnostic in a named file under `warehouse/scripts/slice4/` with a timeout and a row limit, and
  leave no Python process running. Query helpers: `warehouse/scripts/slice2/run_sql.py`,
  `run_sql_vars.py`, `export_query.py`.
- No network calls. No `git stash`. Do not revert or stage anything you did not write: the tree is
  dirty with other people's work. Stage files by path.
- Do not spawn subagents from inside a task.
- ASCII only in SQL comments, logs and docs.
- dbt style follows the existing models: leading commas, one model one decision, a comment at the
  top saying what the model decides, tests in the `.yml` beside the models, hand-written tests in
  `warehouse/tests/`. Measured conditions use a baseline test with a ceiling in `dbt_project.yml`
  (`baseline_max`), set to the measured count.
- The full build must end with `ERROR=0`. Last result before this slice (2026-11-23):
  `PASS=534 WARN=46 ERROR=0 TOTAL=580`. Python tests: 144. CI fixture build: 281, drift step 2,
  last step 24, all passing.
- Commit at the end of each task, with a subject line and two to four bullets, ending with the
  attribution lines the controller gives in the dispatch.
- Controller ledger: `.superpowers/sdd/2026-11-23-slice4-rates-plan/progress.md`. Every ruling made
  without the owner is a `Ruling:` line with its cost if wrong.

## File map

| File | Responsibility |
|---|---|
| `seeds/concept_map.csv` (modify) | The cash-pay rate concept gets its own field, so the two rate tags are read apart |
| `models/intermediate/int_field_read.sql` (modify) | Also the filed value of each rate field and the maturity date |
| `models/intermediate/int_field_rule.sql` (modify) | Also which rule applies to each rate field |
| `models/intermediate/int_field_normalised.sql` (modify) | Also the canonical all-in rate, cash leg, PIK rate, kind, spread, maturity date |
| `seeds/reading_action.csv`, `seeds/action_field.csv`, `seeds/field_rule_default.csv` (modify) | The rate actions marked built; which field each acts on; the default for a pure rate |
| `models/intermediate/int_source_row.sql` or a new small model (Task 1) | The flag on JV commitment lines whose fair value is printed twice |
| `models/intermediate/cmp_rate.sql` (new) | This layer against production, per position and rate field, with a cause |
| `docs/baseline_rates_2026-11-23.md` (new) | Counts, causes, what was not checked |

---

### Task 1: Opening items: the five parked defects and the JV commitment-line flag

**Files:**
- Modify: `warehouse/models/intermediate/int_field_rule.sql`, `_intermediate.yml` (comment fix)
- Modify: `warehouse/scripts/slice3/q_fw_f4_subtotal_with_filer_cost.sql` (comment fix)
- Modify: `warehouse/tests/int_field_normalised_names_rule.sql`
- Modify: `warehouse/models/intermediate/cmp_amount.sql`, `warehouse/dbt_project.yml` (one ceiling
  split in two)
- Create: one test under `warehouse/tests/` (tie-break with an undecidable loser)
- Modify or create: the model that carries the JV commitment-line flag, its `.yml` entry, one test,
  one ceiling
- Create: `warehouse/scripts/slice4/` snapshot queries

**Interfaces:**
- Consumes: the models as they stand at commit `b48df816`.
- Produces: `is_repeated_commitment_value` (boolean, not null) on position rows, readable by slice 6.
  Decide in the task whether it is a column of `int_source_row` or a small model keyed by
  `accession`, `context_id`; say which and why in the report.

**Requirements:**
- The five parked items (`HANDOFF.md`, "Parked for the opening of the slice 4 plan"):
  (a) `int_field_rule.sql:19` and `_intermediate.yml:326` name a test file that does not exist; the
  real one is `tests/baseline_int_field_rule_tie_break_different_effect.sql`;
  (b) `scripts/slice3/q_fw_f4_subtotal_with_filer_cost.sql` has two fund names in SQL comments:
  remove them;
  (c) `tests/int_field_normalised_names_rule.sql:22` is null-unsafe: a null value with a null reason
  passes. Make it fail, and show a hand-made failing row in the report;
  (d) the 2 dollar principals moved by the correction check share the `not_yet_explained` ceiling
  (16) with the 14 others: give `correction_loaded_value_not_matched` its own ceiling (2) and lower
  the other to 14;
  (e) a tie-break whose only losing rule is undecidable is not checked: add a test, ceiling 0.
- JV commitment-line flag (owner decision 2026-11-23: flag now, keep or drop decided after
  reproduction). Background: on HPS JV schedules a commitment line prints the fair value of the
  undrawn delayed-draw tranche that is also printed on its own line; both pipelines carry it twice
  on 24 of 35 lines (`baseline_amounts_2026-11-22.md`). The flag must be decided from structure
  (a row features test: same scope, a commitment line, and a fair value equal to another line's of
  the same borrower in the same schedule), not from a fund name or a list of rows. If the structure
  test needs a per-fund pattern, it is a `reading_rules` entry in that fund's wrapper copy with
  label examples, as slice 2 did. Report the rows flagged per fund and quarter, open the printed
  rows of at least two quarters, and say how many of the 24 are found and what else is caught. The
  flag changes no role, no value and no published set.
- **Nothing else moves.** Snapshots before and after of `int_source_row` (all columns that existed),
  `cmp_row_set`, `int_field_read`, `int_field_rule`, `int_field_normalised`; `cmp_amount` may change
  only in nothing (item (d) changes ceilings, not rows). Show the diffs are empty.

**Done when:** the five items are each shown done, the flag's count and evidence are in the report,
the diffs are empty, the build ends `ERROR=0`, and the work is committed.

---

### Task 2: Field read for rates and maturity

**Files:**
- Modify: `warehouse/seeds/concept_map.csv`, `warehouse/seeds/_seeds.yml`
- Modify: `warehouse/models/intermediate/int_field_read.sql`, `_intermediate.yml`
- Modify, only as far as the concept-map change requires: `int_context_feature.sql`, `cmp_row_set.sql`
- Create: `warehouse/tests/int_field_read_*.sql`, `baseline_int_field_read_*.sql`; ceilings

**Interfaces:**
- Consumes: `int_source_row` (rows with `role = 'position'`), `concept_map`, `stg_filed_fact`,
  `stg_filed_unit`, `stg_filed_fact_placement`, `stg_filed_document_row`.
- Produces: `int_field_read` gains five fields, one row each per position row, present or not:
  `interest_rate_tag` (concept `InvestmentInterestRate`), `interest_rate_cash_tag` (concept
  `InvestmentInterestRatePaidInCash`), `pik_rate`, `spread`, `maturity_date`. Same columns as today,
  plus `value_date` (date, filled only for `maturity_date`; `value_filed` stays null there). The
  two `_tag` names say these are the tags as filed, before any reading decides which leg they hold.

**Requirements:**
- Concept map: today the field `rate` holds both the interest-rate concept and the cash-pay concept
  (slice 3 ruling: one definition of "rate" for the row-set check). The read must keep them apart.
  Add the distinction without changing what `int_context_feature.has_rate` and the `cmp_row_set`
  rate check see: both keep reading the two concepts as "a rate". Say how (a second column in the
  seed, or two fields and a group) and show `int_context_feature` and `cmp_row_set` are row-for-row
  unchanged.
- Spec 6.3 as in slice 3: two facts of one concept on one context with different values make the
  field `unresolved`; the same value twice is `read` with `fact_count` 2; a nil fact is `read` with
  a null value and `is_nil` true.
- `value_filed` is the number as filed: a rate tagged 0.0925 stays 0.0925 here. No times 100.
- Maturity: read the date as filed. Report how the filed layer stores a date fact (read
  `filed_layer.md`), and how many maturity facts do not parse as a date; those are `unresolved` with
  a reason, under a ceiling.
- Units: report the units seen per field with counts per fund (`pure`, `xbrli:pure`, a percent unit,
  none). A filer writing the prefix gets no unit kind today (slice 3 deferred item): list the rows,
  do not fix it here unless the count for the five funds is above zero, in which case stop and ask
  the controller.
- Tests: key unique; the number of rows per position row is fixed (ten: five amount fields, five
  here); `status` in its list; `read` has a `fact_id` and a `read_rule_id`; `absent` has neither.
  Baseline tests with ceilings: `unresolved` per new field.
- Report, per fund and field: read, absent, unresolved, nil. Also, per fund: how many positions
  carry the interest-rate tag only, the cash-pay tag only, both, the PIK tag only, PIK with either.
  Task 3's rules must cover every combination that occurs.
- This task does not read `stg_holdings`.
- Amount rows of `int_field_read` are row-for-row unchanged (snapshot diff empty).

**Done when:** the build ends `ERROR=0`, the report gives the counts, the unit table and the tag
combinations, the diffs are empty, and the work is committed.

---

### Task 3: Conversion of rates

**Files:**
- Modify: `warehouse/models/intermediate/int_field_rule.sql`, `int_field_normalised.sql`,
  `_intermediate.yml`
- Modify: `warehouse/seeds/reading_action.csv` (the six rate actions marked built in slice 4),
  `seeds/action_field.csv`, `seeds/field_rule_default.csv`
- Modify, only if a loaded rule lacks a selector the model needs: `warehouse/readings_loader/` with
  tests in `warehouse/pytests/`
- Create: `warehouse/tests/int_field_normalised_*.sql`, `baseline_int_field_*.sql`; ceilings
- Create: `warehouse/docs/owner_review_rate_readings_2026-11-23.md`

**Interfaces:**
- Consumes: `int_field_read` (Task 2), `stg_reading_rule`, the seeds. Rules loaded today (2026-11-23):
  `rate_is_all_in` for Ares, BCRED, Apollo and HPS (Blue Owl declares no rate reading);
  `pik_only_is_coupon` for Ares, Blue Owl, Apollo, HPS and `pik_only_is_margin` for Blue Owl and
  HPS, each selected by the row feature `pik_tag_only`; `printed_margin_cash_plus_pik` for Blue Owl
  and Apollo. Two wrapper entries are NOT loaded because they need a procedure: Ares
  `rate_only_contexts adopt_adjacent`, HPS `pik_margin_reading whole_coupon`.
- Produces: `int_field_normalised` gains these fields, one row each per position row:
  `interest_rate` (the all-in rate, percent), `interest_rate_cash` (the cash leg, percent),
  `pik_rate` (percent), `spread` (percent), `maturity_date` (in a new column `value_date`), and a
  text column `rate_kind` on the `interest_rate` row (`all_in`, `cash`, `unresolved`). Same
  `action`, `rule_id`, `status`, `reason` columns as amounts.

**Requirements:**
- Read production's code before writing each action and say in the report where its meaning was
  taken from (file and function). Start from `pipeline/source_encodings.py` (`filed_rate_reading`,
  `pik_only_tag_reading`, `printed_margin_reading`, `pik_margin_reading`) and the financial contract
  of 2026-10-06 (`docs/agent_changelog.md`, entries of 2026-10-06 and 2026-11-13;
  `pipeline/financial_conventions.py`, `pipeline/financial_finalization.py`). Do not infer an
  action's meaning from production's values.
- `fraction_to_percent` is the global default for a rate, PIK rate or spread tagged as a pure
  number: a row of `seeds/field_rule_default.csv`, not an `else` branch. State how a filer that
  already tags a percent would be recognised, and count the rows of the five funds where the tagged
  value is above 1 (candidates for "already a percent"): list them, do not rescale them by size.
  A rule that decides scale from the size of a number is a value-size rule: it needs a filer rule
  with evidence from the filing, and goes in the owner-review file.
- `rate_is_all_in`: the interest-rate tag is the all-in rate; the cash leg is all-in less the PIK
  rate where a PIK rate is read, else equal to it. `rate_is_cash_leg`: the tag is the cash leg; the
  all-in rate is the cash leg plus the PIK rate. Where both the interest-rate tag and the cash-pay
  tag are filed, say what production does and reproduce it; if the two tags and the PIK tag do not
  add up, the rate is `unresolved` with reason `legs_do_not_add`, counted under a ceiling.
- No rate reading declared (Blue Owl today): `interest_rate` is `unresolved`, `rate_kind`
  `unresolved`, no value. This is the expected result, not a defect. Report the count per fund.
- `pik_only_is_coupon` / `pik_only_is_margin`: a row that carries only a PIK tag (row feature
  `pik_tag_only`). Two funds carry both rules at the same priority on the same feature: read the
  wrapper and production's code to find what separates them (the rule's parameter, a second
  feature, dates). If nothing loaded separates them, the rows are `rule_conflict`: stop and report
  to the controller with the count. Do not pick one.
- `printed_margin_cash_plus_pik` acts on the spread: the printed margin is cash plus PIK. State
  exactly what is stored as the spread under it, from production's code.
- The two entries that need a procedure are not built here. Measure which rows each would touch
  (per fund and quarter) and list them; Task 4 will name them as a cause. If either turns out to be
  expressible as a rule on row features with no procedure, say so and stop for a controller ruling.
- The check "cash leg plus PIK equals all-in" (spec section 7) blocks the build: on every row where
  all three are `normalised`, `abs(cash + pik - all_in)` is at most a stated tolerance (state it and
  why; float rounding only). Add one hand-made row that must fail it, as a dbt unit test.
- Rate bound (spec section 7): a rate, PIK rate or spread outside 0 to 40 after conversion is a
  finding for slice 6. Here: a baseline test with a ceiling per field and the rows listed. It is a
  sanity bound only; it does not show a rate inside it is right.
- Maturity: `as_filed`. A maturity before the report date is counted and listed (not changed).
- Spec section 10 is NOT built: no rate is derived from base rate plus spread. A test fails the
  build if any `interest_rate` value has an action outside the six rate actions and `as_filed`.
- Tests: every `normalised` value names a rule and an action in the seed; a dbt unit test per rate
  action on a hand-made case, each with one case the action must NOT touch (for example a row with
  both tags under `pik_only_is_coupon`). Baseline tests with ceilings: `unresolved` per field and
  reason.
- `owner_review_rate_readings_2026-11-23.md`: every loaded rate rule, the fund, what it does, the
  rows it decides per quarter, three example rows with the printed text beside the tag; and every
  place a reading rests on an assumption (all quarters assumed, no dates in the wrapper).
- This task does not read `stg_holdings`.
- Amount rows of `int_field_rule` and `int_field_normalised` are row-for-row unchanged.

**Done when:** every rate action has a unit test, the legs check passes, the two unbuilt procedures
are measured, the owner-review file is written, the build ends `ERROR=0`, and the work is committed.

---

### Task 4: Comparison of rates with production

**Files:**
- Create: `warehouse/models/intermediate/cmp_rate.sql`
- Modify: `warehouse/models/intermediate/_intermediate.yml`, `warehouse/dbt_project.yml` (ceilings)
- Create: `warehouse/tests/baseline_cmp_rate_*.sql` (reuse
  `tests/generic/baseline_cmp_amount_cause.sql` if it fits), `warehouse/tests/cmp_rate_key_and_cause.sql`
- Create: `warehouse/docs/baseline_rates_2026-11-23.md`

**Interfaces:**
- Consumes: `int_field_normalised` (Task 3), `cmp_row_set` (rows with `side = 'both'`, both bases),
  `cmp_excluded_quarter`, `stg_holdings`, `stg_correction`.
- Produces: `cmp_rate`, one row per `accession`, `context_id`, `field` for rows on both sides, with
  the columns of `cmp_amount` (`value_new`, `value_production`, `difference`, `outcome`, `cause`,
  `cause_detail`, and the text pair for `rate_kind`).

**Requirements:**
- Join to production on `accession_number` and `src_context_id`, as `cmp_amount` does. Quarters in
  `cmp_excluded_quarter` stay out.
- Field pairs (this layer to `stg_holdings`): `interest_rate` to `interest_rate`;
  `interest_rate_cash` to `interest_rate_cash`; `pik_rate` to `pik_rate`; `rate_kind` to
  `interest_rate_kind` (text); `spread` to `basis_spread`; `maturity_date` to `maturity_date`.
  Production also has `interest_rate_reported`, `basis_spread_kind` and `maturity_precision`: read
  what each holds and say whether it is a second measure, a pair, or out of scope. The reference
  rate type and source are text fields: out of scope (second spec).
- D1: rates are measured differences. State the tolerance for "equal" and why (the same tag times
  100 on both sides: float rounding only; anything larger is a difference). Maturity: equal dates.
- Every `differs`, `new_empty` and `production_empty` row gets a cause through a rule on row
  features, never a list of ids. Expected sources, each to be confirmed against the data, not
  assumed: a correction production applied (`corrected_fields`, `stg_correction`) is
  `needs_correction`; the two wrapper procedures not loaded are `needs_store_not_loaded`; a rate
  production settled with its SOFR reference (`pipeline/sofr_reference.py`) is to be identified and
  given a cause after reading the code; a rate production carried from an adjacent context is the
  Ares procedure. Open the filing rows for a sample of each group before naming a cause, and say
  how many were opened.
- If a group shows a defect in Task 2 or Task 3 (`new_wrong`), do not patch it here: list it with
  the rows and the fix. The controller decides.
- Baseline tests with ceilings: one per basis, field and cause. Each set to the measured count.
- `baseline_rates_2026-11-23.md`: per fund and field, the counts by outcome; the causes with counts
  and evidence; the Task 2 and Task 3 unresolved counts; the legs check; what was not checked.
  Plain language, short sentences, tables for numbers. It states that agreement is not
  correctness, and names what this comparison cannot see: a rate both pipelines read wrongly in the
  same way, and a rate missing on both sides.
- Report beside the comparison, as evidence for the owner and not as a change: per fund at
  2026-03-31, published loans with a rate on this side, with a rate in production, and with a
  spread but no rate (the rows spec section 10 would later fill).

**Done when:** every differing row has a cause, the baseline file is written, the build ends
`ERROR=0`, and the work is committed.

---

### Task 5: CI fixture, and records

**Files:**
- Modify: `warehouse/ci/` (fixture, `run_fixture_build.py`, `README.md`, the expected-values tests)
- Modify: `warehouse/README.md`, `warehouse/docs/HANDOFF.md`, `warehouse/docs/intermediate_spine.md`
  (status line, section 6.4 "as built" table for the rate actions)
- Modify: `docs/agent_changelog.md` (append one entry at the end; touch nothing else in it)

**Interfaces:**
- Consumes: the models of Tasks 1 to 4.

**Requirements:**
- The CI fixture covers the rate fields: at least one fixture position with an all-in rate and a
  PIK rate (so the legs check runs on real fixture rows), one with only a PIK tag, one with no rate
  reading (unresolved), and one maturity date. `cmp_rate` is left out, as `cmp_amount` is. Extend
  the expected-values test for the fixture's rates.
- Prove the fixture commands locally in an empty folder:
  `warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>`.
- After the push (owner's go needed), check the `warehouse` job with `gh run view` and state its
  result. The other two CI jobs fail for older, unrelated reasons: report their state only.
- `README.md`: a short section on how a rate is read and converted, in the plain style of the
  existing sections, in dbt terms a newcomer can follow (the owner is learning dbt): what the three
  stored rates are, what "unresolved" means, and why a missing rate is not "no rate".
- `HANDOFF.md`: a dated section with the state after slice 4, the counts, the open owner decisions,
  the rulings made without the owner (each with its cost if wrong), and what slice 5 (corrections)
  is. Slice 5 opens with: the list of correction stores for the five funds (spec section 11), the
  Apollo zero-value positions published at 0, and the one-time trace of the 14 BCRED
  structured-credit principals (owner decisions 2026-11-23).
- Changelog entry: what was added, the counts, the build result, and the sentence that a passing
  build and agreement with production are not statements that the data is correct.

**Done when:** the local proof of the CI commands is in the report, the build ends `ERROR=0`, and
the work is committed.

---

## Owner decisions this plan may raise

Listed now so they are not a surprise. Each is put to the owner at the end of the slice, with the
measured counts, unless it blocks a task.

1. The two wrapper entries that need a procedure (Ares rate carried from an adjacent context, HPS
   whole-coupon PIK reading): build each as a general mechanism, or leave the rows as a named
   difference until slice 5.
2. Rows where the two rate tags and the PIK tag do not add up.
3. Any filer whose tagged rate is already a percent.
4. Whether Blue Owl gets a rate reading at all (production has none; spec section 10 is the later
   route).

## Self-review (2026-11-23)

- Spec coverage: 6.3 for rate fields (Task 2); 6.4 rate actions and the canonical all-in, cash and
  PIK fields (Task 3); section 7 checks that apply to rates: every value names a rule, cash plus
  PIK equals all-in (blocking), unresolved ceilings, the 0 to 40 bound as a count (Task 3);
  section 8 for rates as measured differences (Task 4). Not in this slice, by the spec's order of
  work: corrections (slice 5); `int_observation`, `int_reading_finding`, the bound and the
  printed-against-tagged check as findings (slice 6); section 10, derived rates (after
  reproduction); the reference rate, floor and other text fields (second spec).
- Owner decisions of 2026-11-23 placed: the JV commitment-line flag (Task 1); Apollo zero-value
  positions and the BCRED trace (named in Task 5 as the opening of slice 5); D17 (unit-count
  principals) waits for the text spec and is untouched here.
- Names are consistent across tasks: `interest_rate_tag`, `interest_rate_cash_tag` (read);
  `interest_rate`, `interest_rate_cash`, `pik_rate`, `spread`, `maturity_date`, `rate_kind`,
  `value_date` (normalised); `cmp_rate`; `is_repeated_commitment_value`.
- Not verified while writing this plan: how production treats a row with both rate tags; what
  separates `pik_only_is_coupon` from `pik_only_is_margin` where one fund declares both; how the
  filed layer stores a date fact. Each is a stated requirement to find out, in Tasks 2 and 3.
