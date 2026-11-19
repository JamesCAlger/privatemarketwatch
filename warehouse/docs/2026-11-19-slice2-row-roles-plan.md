# Slice 2 plan: filing selection and row roles

Date: 2026-11-19. Owner said "do it; subagent-driven" on 2026-11-19.

**Goal.** Decide which filing speaks for each fund and quarter, give every context of every parsed
filing one role, and compare the resulting set of position rows with production's.

**Architecture.** dbt models under `warehouse/models/intermediate/`, reading the filed-layer staging
views (`stg_filed_*`), the readings staging views (`stg_reading_rule`, `stg_correction`) and, for the
comparison only, `stg_holdings`. Rules that are text patterns live in a seed or the rule table, not
in SQL.

**Tech stack.** dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3, Python 3.13 in `warehouse\.venv`.

**Spec.** `warehouse/docs/intermediate_spine.md`, sections 5, 6.1, 6.2, 7, 8 and decisions D1, D3,
D5, D7. Read it. Where this plan and the spec disagree, the spec wins.

## Global Constraints

- Scope is the five v0.5 funds (`stg_v05_scope`). Nothing outside `warehouse/`, except one appended
  entry in `docs/agent_changelog.md` in the last task. Do not edit `AGENTS.md`, `pipeline/`,
  `data/`, `scripts/`, `tests/` or any wrapper.
- This slice decides roles only. It does not read or convert any value field beyond what a role
  rule needs (fair value and cost for the sum rule). No correction is applied.
- Position ids are not produced here. The comparison joins to production on accession and context.
- A context whose role cannot be decided is `unresolved`. It is never forced into another role to
  make the comparison match. Do not tune a rule to one fund's rows: a rule is either general, or it
  is a filer rule in the rule table with its origin named.
- Reproduction (D1): the set of position rows on the published basis must equal production's. Every
  row on one side only is listed with its role, the rule that decided it, and a cause from this
  list: `old_wrong`, `new_wrong`, `convention`, `needs_store_not_loaded`, `needs_correction`,
  `not_yet_explained`. Counts go in a dated baseline file. A cause is evidence, not a guess: say
  what was checked.
- Agreement with production shows the two agree. It does not show either is right. Say so wherever
  a result is reported.
- Run dbt only through `.\warehouse\dbt.ps1` from the repository root (PowerShell). Python only
  through `warehouse\.venv\Scripts\python.exe`. Never `pip install` anywhere.
- No inline Python: no `python -`, `python -c`, heredocs or here-strings piped to Python. Put any
  diagnostic in a named file under `warehouse/scripts/slice2/` with a timeout, and leave no Python
  process running.
- No network calls. No `git stash`. Do not revert or stage anything you did not write: the tree is
  dirty with other people's work. Stage files by path.
- Do not spawn subagents.
- ASCII only in SQL comments, logs and docs.
- dbt style follows the existing models: leading commas, one model one decision, a comment line at
  the top saying what the model decides, tests in a `.yml` next to the models, hand-written tests in
  `warehouse/tests/`. Measured conditions use a baseline test with a ceiling in
  `dbt_project.yml` (`baseline_max`), as `tests/baseline_*.sql` do.
- The full build must end with `ERROR=0`. Last result before this slice:
  `PASS=190 WARN=10 ERROR=0 TOTAL=200`. Python tests: 97.
- Commit at the end of each task, with a subject line and two to four bullets. End the message with:
  `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

### Task 1: Context features and filing selection

**Files:**
- Create: `warehouse/models/intermediate/int_context_feature.sql`
- Create: `warehouse/models/intermediate/int_filing_candidate.sql`
- Create: `warehouse/models/intermediate/int_filing_selected.sql`
- Create: `warehouse/models/intermediate/_intermediate.yml`
- Create: `warehouse/tests/` tests named `int_filing_*.sql` and `baseline_int_filing_*.sql`
- Modify: `warehouse/dbt_project.yml` (materialisation for `intermediate`, ceilings)

**Interfaces:**
- Consumes: `stg_filed_filing`, `stg_filed_context`, `stg_filed_context_member`, `stg_filed_fact`,
  `stg_holdings`, `stg_v05_scope`.
- Produces:
  - `int_context_feature`, one row per `accession`, `context_id`, structure only, no judgement:
    `cik`, `instant_date`, `period_type`, `member_count`, `has_identifier_member` (a member on an
    axis whose local name is `InvestmentIdentifierAxis`), `identifier_label` (that member's text, as
    filed), `other_axes` (list of the other axes), `other_members` (list), `is_filing_period_end`
    (`instant_date` equals the filing's `document_period_end_date`), `fair_value` and `cost` (the
    fact values on the context, null where absent or where two facts of the concept disagree, with
    `fair_value_fact_count` and `cost_fact_count`), and one boolean per term fact present:
    `has_principal`, `has_shares`, `has_rate`, `has_spread`, `has_pik_rate`, `has_maturity`, plus
    `has_term_fact`.
  - `int_filing_candidate`, one row per parsed filing: `cik`, `accession`, `report_date`,
    `document_type`, `amendment_flag`, `position_fact_count`, `numeric_fact_count`.
  - `int_filing_selected`, one row per `cik`, `report_date`: `accession`, `selection_rule`,
    `candidate_count`; and a row per refused quarter with `accession` null and `refusal_reason`.

**Requirements:**
- Concept names for fair value, cost and each term fact: take them from how the filed layer's bridge
  tests and `stg_holdings` already identify them (`warehouse/tests/baseline_filed_fair_value_*.sql`,
  `filed_layer.md` section 7 ruling 12: match on local name plus the `us-gaap` namespace, never on
  prefix). List the concepts you used in the model's comment and in the report. If a term fact has
  more than one concept in use across the five funds, list each and say how you found it.
- Filing selection is ported from the pilot. Read it first:
  `git show filer-profile-pilot:scripts/profile_pilot/instance_select.py`. Rule (spec 6.1): count
  position facts per candidate filing for a fund and report date; the latest filing at least 90 pct
  as full as the fullest wins; an amendment with no numeric facts is skipped; anything in between,
  two originals, or a period-end mismatch is refused with a reason. The 90 pct is a project variable
  (`filing_fullness_min`), not a literal in SQL.
- Tests: keys unique and not null; every selected accession is a parsed filing; one row per fund and
  report date. Baseline tests with ceilings: quarters refused; quarters where the selected accession
  differs from the accession production's holdings use for that fund and date; quarters production
  has and this model does not, and the reverse.
- Report the comparison with production as a table per fund, and explain every differing quarter by
  looking at the candidates. `HANDOFF.md` notes three cached Q3-2026 10-Qs not in production and
  seven empty amendments: say whether your result agrees.
- `intermediate` models are materialised as tables.

**Done when:** the build ends `ERROR=0`, the report lists every difference in selection with its
cause, and the work is committed.

---

### Task 2: Row roles

**Files:**
- Create: `warehouse/seeds/role_pattern.csv` and its entry in `warehouse/seeds/_seeds.yml`
- Create: `warehouse/models/intermediate/int_source_row.sql` (helper models `int_role_*.sql` allowed,
  one decision each)
- Modify: `warehouse/models/intermediate/_intermediate.yml`
- Create: tests named `warehouse/tests/int_source_row_*.sql`
- Create, only if rule 6 needs it: `warehouse/roles/subtotal.py` with tests in
  `warehouse/pytests/test_roles_subtotal.py`

**Interfaces:**
- Consumes: `int_context_feature`, `int_filing_selected` (Task 1); `stg_reading_rule`.
- Produces: `int_source_row`, one row per `accession`, `context_id` for every context of every
  parsed filing of the five funds: `cik`, `role` (`position`, `aggregate`, `comparative`,
  `superseded`, `not_schedule`, `unresolved`), `role_rule` (which numbered rule decided),
  `rule_id` (the rule-table or seed row used, where one was), `reason` (short text),
  `scope` (`fund`, or the JV or entity name), `is_cash`, `is_published` (false for a JV's own
  schedule rows, matching production's published basis), and `cross_check_agrees`.

**Requirements:**
- Rules 0 to 9 exactly as in spec section 6.2, first match decides, in that order. Read the pilot's
  version first: `git show filer-profile-pilot:scripts/profile_pilot/census_published.py` (rules R1
  to R7 and R5b, version 2). Where the pilot and the spec differ, follow the spec and say so in the
  report.
- Text patterns for rules 4 and 5 (total, subtotal, net assets, affiliation headings, cash and cash
  equivalents, the money-market exception) are rows in `seeds/role_pattern.csv` with columns
  `pattern_id`, `rule_number`, `pattern` (a regular expression), `role`, `note`. They are global: no
  fund's name or label appears in them. The SQL holds no label text.
- Rule 7 (JV entity) and the cash identifiers use the loaded filer rules in `stg_reading_rule`
  (`set_scope`, `set_scope_by_label_suffix`, `set_scope_by_identifier_suffix`, `detached_schedule`,
  `set_is_cash`). Do not copy their values into SQL or the seed.
- Rule 6 (a row whose label starts other rows' labels and whose fair value, and cost, equals their
  sum) with its guard: a row that reports a rate, spread, PIK rate or maturity, or whose fair value
  is zero, is never removed. Try it in SQL first. If the level-by-level repeat is awkward, write it
  as a small Python step whose output dbt reads, with tests, and say why in the report.
- Cross-check: a position should carry at least one term fact. Where the cross-check and rules 4 to
  6 disagree, the role is `unresolved` (spec 6.2).
- Tests: exactly one role per context; `role` and `role_rule` in their lists; every `rule_id` given
  resolves to the seed or the rule table; a context of a non-selected filing is `superseded`; a
  `position` has a fair value. A baseline test with a ceiling for the count of `unresolved`.
- Unit-test the rules on a small hand-made case where SQL allows it (a dbt unit test or a seed-like
  fixture), including at least one false-positive case for each text pattern: a real position whose
  label contains "total" or "cash" must stay a position.
- Do not look at production's holdings to decide a role. This task does not read `stg_holdings`.
- Report counts by fund, role and rule.

**Done when:** the build ends `ERROR=0`, the report gives the role counts, and the work is committed.

---

### Task 3: Row-set comparison with production

**Files:**
- Create: `warehouse/models/intermediate/cmp_row_set.sql`
- Modify: `warehouse/models/intermediate/_intermediate.yml`
- Create: `warehouse/tests/baseline_cmp_row_set_*.sql`
- Create: `warehouse/docs/baseline_roles_2026-11-19.md`
- Modify: `warehouse/dbt_project.yml` (ceilings)

**Interfaces:**
- Consumes: `int_source_row` (Task 2), `int_filing_selected` (Task 1), `stg_holdings`,
  `stg_correction`.
- Produces: `cmp_row_set`, one row per `accession`, `context_id` that is a published position on
  either side: `cik`, `report_date`, `side` (`both`, `new_only`, `production_only`), the new layer's
  `role`, `role_rule`, `reason`, `is_published`, production's `accounting_record_class` and
  `fair_value`, and `cause`.

**Requirements:**
- Production's side: `stg_holdings` rows on the published basis
  (`accounting_record_class <> 'underlying_schedule'`), keyed by `accession_number` and
  `src_context_id`. Rows with no context id are counted and listed separately.
- The new side: `int_source_row` rows with `role = 'position'` and `is_published`.
- Report per fund and in total: both, new only, production only, and the fair value on each side.
  Also compare the unpublished rows (JV schedules) the same way, as a second table.
- For every one-sided group, find the cause and record it in `cmp_row_set.cause` through a rule
  expressed on row features, not a list of ids. Use the causes in Global Constraints. Open the
  filing rows (`stg_filed_document_row`, `stg_filed_fact_placement`) for a sample of each group
  before naming a cause, and say how many you opened. Where a group is explained by a store slice 1
  did not load (`data/overrides/bdc_aggregate_row_overrides.json`,
  `data/overrides/bdc_xbrl_html_section_bridges/`, or the wrapper's `dispatch` section), read the
  store to confirm, name the entries, and mark it `needs_store_not_loaded`. Do not load the store in
  this task.
- If a group shows a defect in a Task 2 rule (cause `new_wrong`), do not patch it here: list it in
  the report with the rows and the fix you would make. The controller decides.
- Baseline tests with ceilings: `new_only`, `production_only`, and `not_yet_explained`, each set to
  the measured count.
- `baseline_roles_2026-11-19.md`: the tables above, the causes with counts and evidence, the
  unresolved count from Task 2, the filing-selection differences from Task 1, what was not checked.
  Plain language, short sentences, tables for numbers. State that agreement is not correctness.

**Done when:** the build ends `ERROR=0`, the baseline file is written, every one-sided row has a
cause, and the work is committed.

---

### Task 4: Fixture build for CI, and records

**Files:**
- Create: `warehouse/ci/` with a small committed fixture and `warehouse/ci/README.md`
- Modify: `.github/workflows/ci.yml` (the `warehouse` job)
- Modify: `warehouse/README.md`, `warehouse/docs/HANDOFF.md`
- Modify: `docs/agent_changelog.md` (append one entry at the end; touch nothing else in it)

**Interfaces:**
- Consumes: the models of Tasks 1 to 3.

**Requirements:**
- A fixture small enough to commit (well under 1 MB) that lets `dbt build` run for the staging views
  of the filed layer and readings and the `intermediate` models, on a clean machine with none of the
  repository's data. Build it from the committed parser fixtures in `warehouse/pytests/fixtures/` by
  running the parser and the loader on fixture inputs inside the CI job, or commit the small Parquet
  outputs; choose the one that needs less upkeep and say why. Paths come from dbt variables
  overridden on the command line (`--vars`), not from edits to the models.
- The marts and the models that read `data/output/` are left out of the CI build by selection. Say
  exactly which selection the job runs and what it does not cover.
- Prove the job's commands work locally, in a temporary folder, before writing them into the
  workflow. The workflow itself cannot be run here: say so.
- `README.md`: a short section on the intermediate layer in the same plain style as the existing
  sections, explaining role, selected filing and the comparison in dbt terms a newcomer can follow.
- `HANDOFF.md`: update the 2026-11-19 section with the state after slice 2 and what slice 3 is.
- Changelog entry: what was added, the counts, the build result, and the sentence that a passing
  build and agreement with production are not statements that the data is correct.

**Done when:** the local proof of the CI commands is in the report, the build ends `ERROR=0`, and
the work is committed.
