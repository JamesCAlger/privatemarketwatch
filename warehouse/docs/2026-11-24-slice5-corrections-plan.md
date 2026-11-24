# Slice 5 plan: corrections

Date: 2026-11-24. The owner asked for slice 5 "as-is" (owner decisions of 2026-11-23 in `HANDOFF.md`).
Status: written for the owner's review. Not started. Branch `warehouse-slice5`, worktree
`.claude/worktrees/warehouse-dbt`.

> For agentic workers: use superpowers:subagent-driven-development to run this plan task by task. One fresh
> implementer per task, who sees only that task's text and the Global Constraints; an independent review after
> each task. Tasks give requirements and SQL shapes, not full code (ledger ruling, slice 2): the SQL depends on
> measured data. Implementers and reviewers run on Sonnet or Opus, never Fable (owner, 2026-11-12).

## Part 1: summary for the owner (two minutes)

**What slice 5 does.** Production fixes some values by hand: about 4,200 entries for the five funds sit in
"correction stores" (CSV files and wrapper entries that say "on this row of this filing, set this field to this
value"). The new layer loads them but does not use them yet, so 716 amount comparisons and 598 rate comparisons
(454 published, 144 in JV schedules) and 52 position rows are marked `needs_correction`. Slice 5 applies those
corrections in a new step, keeps the filed value and the converted value beside the corrected one, and writes
one record per correction saying what happened to it: applied, no change, refused (and why), or failed. Then it
compares with production again.

In dbt terms: a new **model** (a SQL file that dbt turns into a table) resolves each correction to its row, a
second records the outcome per correction, a third holds the corrected value of every field. The comparison
models then read the corrected values. Nothing is applied silently: every outcome is counted, and every count has
a **ceiling** (a number in `dbt_project.yml`; the build fails if the count goes above it).

**Tasks.**

| # | Task | What it adds | What could go wrong |
|---|---|---|---|
| 1 | Housekeeping | Splits the conversion model in two (amounts, rates), moves the unit list to a seed, seven small repairs from the slice 4 review | The split changes a value by accident. Guard: a row-for-row comparison of every table before and after must show zero differences |
| 2 | Inventory and loader | A measured list of every correction store with entries for the five funds; loads the two agent stores' value entries (if you agree, decision 1) | A store whose key cannot be tied to a row without reading printed text |
| 3 | Apply corrections to amounts and to the row set | `int_correction_target`, `int_correction_application`, `int_field_corrected`, `int_row_corrected`. Publishes the Apollo zero-value lines at 0 (your decision of 2026-11-23) | A correction lands on the wrong row (identifier keys), or changes a fair value nobody expected |
| 4 | Corrections on rates; the two wrapper procedures | Rate corrections feed the rate reading, so the cash leg and the rate kind follow. Builds the Ares "rate on the neighbouring context" rule as a general rule. HPS whole-coupon PIK stays a named difference (it needs printed text) | The rate reading gives a different answer on corrected inputs than production's |
| 5 | Compare again; the BCRED trace | `cmp_row_set`, `cmp_amount`, `cmp_rate` read the corrected values. One-hour trace of the 14 BCRED structured-credit principals | Rows turn into `new_wrong` or `not_yet_explained` |
| 6 | Measurements for consolidation, CI fixture, records | How many corrections are pinned to one row versus reusable, and how many repeat the same fix for the same position across quarters (baseline file only, no action); CI fixture rows; handoff, README, spine, changelog | None on data; the definitions of "same fix" miss some repeats (stated) |

**Starting point, measured today (2026-11-24) at HEAD 7eac03c0 after a full rebuild** (`PASS=690 WARN=106
ERROR=0 TOTAL=796`):

- Loaded corrections for the five funds: 4,196. Row corrections 1,413 (all keyed by identifier text), row
  corrections by context 2,498, wrapper entries 285 (64 values, 202 relabels, 3 exceptions, 16 evidence notes).
- Of the 3,975 value corrections: 1,022 set a number this layer holds (fair value, cost, principal, shares,
  share of net assets, rates, spread, maturity), 780 set a companion field (currency, FX rate, FX status, cost
  currency, rate kind, maturity precision), 2,173 set a field this layer does not hold (names, industry, class,
  reference rate text). No two corrections set the same field of the same row to different values (0 conflicts).
- Not loaded: two production stores change the five funds' holdings: `agent_investigate_rules` (12 live rules
  that remove rows, 2 that add 8 Ares positions) and `agent_b2_corrections` (Ares: 1 rate fix on one row, 1 rule
  that removes comparative-period rows in one quarter).
- If each correction replaced this layer's value, 712 of the 716 amount comparisons would carry production's
  value. On rates, PIK rate (158 of 158), spread (265 of 265) and maturity (11 of 11) would; the all-in rate 48 of
  51; the cash leg and the rate kind only once the reading re-runs on the corrected inputs (0 of 68, 15 of 45
  directly).

**Decisions needed before execution starts.** Recommendation first, then the cost of each option.

| # | Question | Recommendation | Cost of the options |
|---|---|---|---|
| 1 | Load the two agent stores? | Load their value entries as corrections (8 Ares positions added by `row_add`, 1 Ares rate fix). Load their row-removing rules into a separate table for the record, not applied: their conditions are written in production's column names, and this layer's row roles already reproduce what they remove (the row sets agree) | Load: one loader change, drift check on 3 more files. Not load: 8 Ares rows and 1 rate stay `needs_store_not_loaded` |
| 2 | 67 corrections keyed by identifier text find no position here by that text (Blue Owl 21, HPS 42: production's identifier drops the member's last segment, for example "\| Non-Affiliated Issuer"; Ares 6, Apollo 1: rows held unresolved here). Find the row through production's holdings row (same filing, same identifier, then its context)? | Yes, labelled `production_bridge`, with its own ceiling (67) | Bridge: the corrections depend on production's file until they are re-keyed by context (before cutover). Refuse: 63 corrections on published rows are not applied and their rows keep a difference. A third route, a fund reading rule that drops the segment, is the clean fix but is a new action for two funds: later |
| 3 | A correction on a field this layer does not hold yet (2,173 values, 202 relabels): what outcome? | A fifth outcome, `deferred`, beside the design's applied / no-op / rejected / failed | `deferred`: the design's list grows by one word. Without it these would be `rejected`, and 2,375 harmless rows would hide the few real refusals |
| 4 | Your 2026-11-23 decision covers the two Apollo rollups. The same wrapper store sets 44 zero fair values (12 contexts under those two rollups across quarters, 32 other lines printed with a dash). Apply all 44? | Yes: one store, one mechanism; a rule must not pick rows from a list | All 44: 32 more zero-value positions published, as production does. Only the 12: needs a list of row ids, which the project rules forbid |
| 5 | The two slice 4 procedures | Build Ares `adopt_adjacent` as a general rule (it needs only structure: neighbouring context numbers and the identifier). Keep HPS whole-coupon PIK as a named difference: it needs the printed row's coupon grammar and production's loan class, neither read by any model | Building whole-coupon now means reading printed text inside the spine, against D2 (text fields are the second spec) |
| 6 | Owner decision 10 (2026-11-23) says "read the unit properly ... mapping moved to data". The filed layer keeps the unit as written (`pure`, `utr:Rate`); it does not keep the namespace behind a prefix. | A seed keyed by the written unit, with `xbrli:pure` and `xbrli:shares` rows, and a test that fails when a filing uses a unit text the seed does not list. 0 rows move on the five funds (no filing writes the prefix) | Reading by namespace needs a parser change (filed layer version 4) and a re-parse of all 86 filings: a separate piece of work |
| 7 | If a context-keyed and an identifier-keyed correction ever set the same field of one row differently (0 today) | Conflict: neither applied, both `rejected`, ceiling 0 | Production lets the context-keyed one win (it is read second). Copying that hides a disagreement between two stores |

**What this slice will not show.**

- That a correction is right. Applying production's corrections makes the two pipelines agree; it does not check
  the correction against the filing. No check here sees a wrong correction.
- That a correction is still needed. The row stores carry no "expected old value" column, so the check "the value
  the correction expected is still there" (spec 6.5) can run only on the 202 relabels. A correction that is no
  longer needed shows only when it changes nothing (`no_op`).
- Anything about the 2,375 deferred corrections (names, classes, industry, reference rate text). They wait for
  the text spec.
- Agreement with production is not correctness: a value both pipelines hold wrongly in the same way counts as
  equal.

## Part 2: the plan

**Goal.** Apply every loaded correction for the five v0.5 funds to the converted values at a declared step, keep
the filed and converted values beside the corrected one, record one outcome per correction, and compare with
production again so that every `needs_correction` row becomes equal or gets a new named cause.

**Architecture.** Four new models after `int_field_normalised`:

```
stg_correction --> int_correction_target --> int_correction_application
                         |                          |
int_source_row ----------+--> int_row_corrected     |
int_field_normalised ----+--> int_field_corrected <-+
                                   |
             cmp_row_set, cmp_amount, cmp_rate (read the corrected values)
```

No role in `int_source_row` changes: a correction that makes a context a position is recorded in
`int_row_corrected`, a separate model. No correction edits a filed or normalised value in place.

**Tech stack.** dbt-core 1.12.7, dbt-duckdb 1.11.1, DuckDB 1.4.3, Python 3.13 in `warehouse\.venv`.

**Spec.** `warehouse/docs/intermediate_spine.md` sections 5, 6 (6.4, 6.5), 7, 8, 11 and decisions D1, D2, D5,
D6, D8, D10, D15, D17, D18, D19; `warehouse/docs/design.md` sections 3 to 5 (Correction, correction_application,
point 5: two kinds of correction). Where this plan and the spec disagree, the spec wins, except where an owner
decision above changes it; the task that builds it amends the spec.

### Terms used here

- **Correction**: one row of `stg_correction`: a filing, a key (context id, or identifier text), a field and a
  value. Kinds: `value`, `relabel`, `exception`, `evidence`, and after Task 2 `add_row`.
- **Target**: the (accession, context id) a correction acts on, after its key is resolved.
- **Step**: where in the chain a correction acts. `filed`: it replaces the filed value and the conversion rules
  run on it. `converted`: it replaces the converted value. `reading_input`: it replaces an input of the rate
  reading, which then re-runs. `row`: it makes a context a position (supplies the fair value or the term fact the
  role rules lacked).
- **Outcome**: `applied`, `no_op` (the target already holds the value), `rejected` (the correction cannot be
  applied as written: target not found, target not a position, conflict, expected value differs), `failed` (it
  could not be executed: value not of the field's type, no FX rate), and `deferred` if decision 3 is taken.

## Global Constraints

Copied from the slice 4 plan (binding), then AGENTS.md, then new for this slice.

- Scope is the five v0.5 funds (`stg_v05_scope`): 0001803498, 0001812554, 0001287750, 0001838126, 0001837532.
- Work only on branch `warehouse-slice5` in the worktree `.claude/worktrees/warehouse-dbt`. Confirm the branch
  (`git branch --show-current`) before the first edit of each task. Nothing outside `warehouse/`, except one
  appended entry in `docs/agent_changelog.md` in Task 6. Never edit `AGENTS.md`. Do not edit `pipeline/`,
  `scripts/`, `tests/` (the repository's), anything under `data/`; production stores under `data/overrides/`
  and everything under `data/output/` are read-only inputs.
- Fund rules live only in the wrapper copies `warehouse/wrappers/<cik>.json`, section `reading_rules` (D10).
  After editing a copy, run `.\warehouse\load_readings.ps1`. No fund's name, CIK, label or concept appears in
  SQL, in a seed, or in Python (comments included, from Task 1 on).
- **No row of a table may change unless the task says so.** A change is a defect to explain, not to absorb. Each
  task proves it with row snapshots of every base table before and after (pattern:
  `scripts/rate_rulings/snapshot_tables.py` and `scripts/slice4/compare_snapshots.py`; Task 1 copies them to
  `scripts/slice5/` and adds named views).
- A field that cannot be decided is left empty with a status and a reason (D5). A correction that cannot be
  applied is recorded with its outcome and reason, never dropped and never forced. An unresolved or rejected
  outcome is a valid result.
- Reproduction (D1): fair value, cost and principal to the dollar; other fields as measured differences. Every
  one-sided row and every differing field has a cause from the closed list `old_wrong`, `new_wrong`,
  `convention`, `needs_correction`, `needs_store_not_loaded`, `production_stale`, `owner_review`,
  `not_yet_explained`. A cause is evidence, not a guess: say what was checked and how many rows were opened.
- Agreement with production shows the two agree. It does not show either is right. No check here detects a wrong
  correction or a value both pipelines read the same wrong way. Say so wherever a result is reported. Nothing is
  tuned to make the comparison look better.
- Ceilings (`baseline_max`, `cmp_*_max`, `cmp_*_detail_max` and the new ones) are set to the measured count.
  Never raised without a stated reason in the comment beside it. A count may fall freely.
- Every value on a published row names the rule it was read under (spec section 7); a corrected value also names
  its `correction_id`. An action not in `seeds/reading_action.csv` fails the build.
- Rule resolution (spec section 5, confirmed 2026-11-23): higher priority wins; at equal priority a rule naming a
  filing beats a rule naming a row feature; two still equal are a conflict. A missing row feature is an error.
- Run dbt only through `.\warehouse\dbt.ps1` from the worktree root (PowerShell). Python only through
  `warehouse\.venv\Scripts\python.exe`. Never `pip install` anywhere.
- No inline Python: no `python -`, `python -c`, heredocs or here-strings piped to Python. Diagnostics are named
  files under `warehouse/scripts/slice5/` (SQL run with `warehouse/scripts/slice2/run_sql.py <file> <max rows>`,
  which has a 300-second timeout), with a row limit; leave no Python process running. No placeholder shell
  commands, no `sleep`.
- No network calls (no SEC EDGAR, no downloads). No `git stash`. Do not revert or stage anything you did not
  write. Stage by explicit path. Never stage `data/overrides/bdc_xbrl_wrappers/0001287750.json` (a change in the
  working tree that is not ours).
- A file whose sha256 is recorded anywhere (a manifest, a test, a doc) needs a `-text` line in the right
  `.gitattributes` (`warehouse/ci/.gitattributes` for the fixture, the root one otherwise) before it is
  committed.
- Do not spawn subagents from inside a task.
- ASCII only in SQL comments, logs and docs.
- dbt style follows the existing models: leading commas, one model one decision, a comment at the top saying what
  the model decides, tests in the `.yml` beside the models, hand-written tests in `warehouse/tests/`.
- The full build must end with `ERROR=0`. Last result before this slice, measured 2026-11-24 at 7eac03c0:
  `PASS=690 WARN=106 ERROR=0 TOTAL=796`. Python tests: 146 passed. CI fixture build, re-run 2026-11-24 in an empty folder: step 4
  `PASS=3`, build `PASS=334 WARN=5 ERROR=0 TOTAL=339`, empty run `PASS=2`, unit and drift step `PASS=35`.
- A seed that gains a column needs `.\warehouse\dbt.ps1 seed --full-refresh --select <seed>` once in an existing
  database.
- Each task ends with `ERROR=0`, its proofs, its docs, and one or more commits. Commit message: a subject line,
  then two to four bullets, then the attribution lines the controller gives in the dispatch. Nothing is pushed.
- Controller ledger: `.superpowers/sdd/2026-11-24-slice5-corrections-plan/progress.md` (git-ignored). Every
  ruling made without the owner is a `Ruling:` line with its cost if wrong.

## How production applies corrections (what each mechanism reproduces)

Read in production's code on 2026-11-24. Order within `pipeline/unified_holdings.py` `build_unified_holdings`
unless stated.

| Store (five funds) | Key | What it can do | Where production applies it |
|---|---|---|---|
| wrapper `untagged_values` (Ares 6, BCRED 1, Apollo 57) | accession, context, field, value, optional currency | Supply a filed value that is printed but not tagged | At parse time: `pipeline/bdc_filings.py` line 1141 `fill_untagged_values` (`pipeline/page_labelled_contexts.py`). Before staging, so conversion runs on it |
| wrapper `relabelled_contexts` (Blue Owl 202) | accession, context, expected label, new identifier | Replace the identifier text | Parse time, `page_labelled_contexts.py` |
| wrapper `pik_margin_reading` "not ACC CTX" (HPS 3) | accession, context | Exempt a row from the whole-coupon reading | `pipeline/whole_coupon_pik.py` `apply` (staging, `staging_bdc.py` lines 3339-3340) |
| wrapper `rate_verification_anchors` (Ares 16) | accession, context, field | Evidence for a check; changes no value | `pipeline/provenance_reverify.py` line 420 (a check) |
| `row_corrections.csv` (1,413) | cik, report date, accession, identifier text (+ optional context, empty for all five funds) | Set or withdraw (empty value) one of the fields in `_CORRECTABLE_FIELDS`; a key matching several rows sets all of them | `_apply_row_corrections`, line 1532, after classification and printed sections (line 1529), before the promoted stores |
| `row_corrections_by_context.csv` (2,498) | same plus context | Same, one context | Same function; read after the first file, so on the same key and field it would win (0 such pairs today) |
| `agent_b2_corrections` (Ares: `all_pik_normalization` 1 row by `row_id`; `comparative_period_filter` 1 quarter) | row_id; report date | Set rate fields on one row; remove comparative-period rows | `agent_promoted.apply_promoted_plan` lines 1545-1556 (value classes); comparative filter at raw staging, line 996 |
| `agent_investigate_rules` (BCRED 2, Blue Owl 4, Ares 6, Apollo 2 live; HPS 0) | a SQL predicate on production's columns, or listed positions | Remove rows (`row_exclusion`, 12), add rows (`row_add`, 2 rules, 8 Ares positions with context ids) | `apply_promoted_plan`: removals first, then adds, then values, then classes (lines 749-772) |
| After all of them | | The rate legs and kind are derived again from the corrected rate, PIK rate and kind | `pipeline/financial_finalization.py` `prepare_artifact`, line 1643 |

Checked and not a holdings correction for the five funds: `bdc_aggregate_row_overrides.json` (7 Ares entries; its
only reader is `pipeline/source_reconciliation.py`, a check); `identifier_spread_corrections.json` (0 entries for
the five); `bdc_xbrl_oracle_exceptions.json` (2 HPS, check decisions); `rate_convention/0001812554.json`,
`identifier_anchors/0001837532.json`, `identifier_rate_grammars/0001837532.json` (readings, not corrections,
design.md section 5 point 5); `verdict_retirements/`, `finding_dispositions/` (decisions).

Production's last application audit (`data/output/agent_fix_application_audit.csv`, 2026-11-16) shows every live
agent rule of the five funds applied (`exclude_prg_rollup_2023q2`: 0 rows, drift `noop`).

## File map

| File | Responsibility |
|---|---|
| `models/intermediate/int_amount_normalised.sql`, `int_rate_normalised.sql` (new, Task 1) | The two halves of today's `int_field_normalised` |
| `models/intermediate/int_field_normalised.sql` (becomes a view, Task 1) | Union of the two, same columns and rows as today |
| `macros/rate_reading.sql` (new, Task 1) | The rate reading, callable on normalised or corrected inputs |
| `seeds/unit_kind.csv` (new, Task 1) | Written unit text to unit kind; replaces the `unit_kind` macro's literals |
| `readings_loader/` (modify, Task 2) | Loads the agent stores' value entries and records their row rules |
| `seeds/correction_field.csv` (new, Task 2) | Correction field to this layer's field, its step, and whether this layer holds it |
| `models/intermediate/int_correction_target.sql` (new, Task 3) | Which row each correction acts on |
| `models/intermediate/int_correction_application.sql` (new, Task 3) | The outcome of each correction |
| `models/intermediate/int_row_corrected.sql` (new, Task 3) | The position set after corrections that make a context a position |
| `models/intermediate/int_field_corrected.sql` (new, Task 3; rates in Task 4) | The corrected value of every field, beside the filed and normalised values |
| `models/intermediate/int_rate_adjacent.sql` (new, Task 4) | Ares `adopt_adjacent`: rate facts carried from the neighbouring rate-only context |
| `cmp_row_set.sql`, `cmp_amount.sql`, `cmp_rate.sql` (modify, Task 5) | Compare the corrected values |
| `docs/baseline_corrections_2026-11-24.md` (new; Tasks 2, 5, 6) | Inventory, outcomes, comparison, consolidation tables |

---

### Task 1: Housekeeping that opens the slice

**Files:**
- Create: `models/intermediate/int_amount_normalised.sql`, `models/intermediate/int_rate_normalised.sql`,
  `macros/rate_reading.sql`, `seeds/unit_kind.csv`, `scripts/slice5/snapshot_tables.py` (copy of
  `scripts/rate_rulings/snapshot_tables.py` that also exports the views named on its command line),
  `scripts/slice5/compare_snapshots.py` (copy of `scripts/slice4/compare_snapshots.py`),
  `pytests/test_detail_ceilings_have_tests.py`, `pytests/test_no_fund_names_in_sql.py`
- Modify: `models/intermediate/int_field_normalised.sql` (becomes the union view), `_intermediate.yml`,
  `macros/field_lists.sql` (`unit_kind` reads the seed), `int_field_rule.sql`, `int_rate_scale.sql` (callers of
  `unit_kind`, if the macro's signature changes), `seeds/_seeds.yml`, `seeds/reading_action.csv`,
  `int_filing_candidate.sql`, `int_role_structure.sql`, `models/marts/fact_fund_period.sql`,
  `tests/baseline_concept_rule_value_and_term.sql` (comments only), `ci/fixture/...` and
  `tests/ci_fixture_expected_rates.sql` (the prefixed-unit row and the new fixture row), `ci/README.md`

**Interfaces:**
- Consumes: the models as they stand at 7eac03c0.
- Produces: `int_amount_normalised` (fields `fair_value`, `cost`, `principal_amount`, `principal_amount_usd`,
  `shares`, `pct_of_net_assets`) and `int_rate_normalised` (fields `interest_rate`, `interest_rate_cash`,
  `pik_rate`, `spread`, `maturity_date`), both with today's columns of `int_field_normalised`: `accession`,
  `context_id`, `field`, `cik`, `report_date`, `value`, `currency`, `value_filed`, `action`, `rule_id`, `status`,
  `reason`, `fx_rate`, `fx_rate_date`, `value_date`, `rate_kind`, `scale_rule_ids`. `int_field_normalised`
  becomes `select * from int_amount_normalised union all select * from int_rate_normalised`, materialized as a
  view. Macro `rate_reading(inputs)` takes a relation with one row per position and the columns the reading reads
  today (rate tag, cash-pay tag, PIK rate and spread in percent with their scale rule ids, the reading rule and
  action, `prints_pik`) and returns the rate rows. Seed `unit_kind` with columns `unit_pattern` (an RE2 pattern
  matched in full against the written unit), `unit_kind` (`usd`, `foreign`, `shares`, `pure`), `note`.

**Requirements:**
- (a) **The split.** Move the amount part and the rate part of `int_field_normalised.sql` into two models; the rate
  reading (the CTEs from `rate_read` to `scaled`) becomes macro `rate_reading`, called by `int_rate_normalised`.
  Accepted ONLY when a row-for-row snapshot diff shows zero rows in one and not the other for every base table and
  for the view `int_field_normalised`. Take the "before" snapshot first, from the build at 7eac03c0. Report the
  per-table counts.
- (b) **Unit kind as data** (owner decision 10, and decision 6 above). Seed rows: `iso4217:USD` usd;
  `iso4217:[A-Z]{3}` foreign; `shares`, `xbrli:shares` shares; `pure`, `xbrli:pure`, `utr:Rate` pure. Ordering:
  a unit matching two patterns is an error (test). Add a test that every unit text read by `int_field_read` for a
  field that takes a unit kind (amounts and rates) matches exactly one row or is listed with kind `other` on
  purpose. The five funds' units today (appendix A8; re-measure with a query under `scripts/slice5/`):
  `iso4217:USD`, `pure`, `utr:Rate`, `iso4217:USD/shares`, `shares`, 17 other currency codes, and 30 other units
  such as `arcc:borrower`. On the five funds 0 rows move (no filing writes `xbrli:`). In the CI fixture the one rate in
  `xbrli:pure` becomes `pure`: update `tests/ci_fixture_expected_rates.sql` and say which row changed.
- (c) **Tie-break order** in `int_field_rule` (top CTE): today `rank_unread_input` is checked before
  `same_rank_count`, so a tie between a rule that needs unread text and a decidable rule reads `text_not_read`.
  New order: `feature_missing`; then, when `same_rank_count > 1` and the top rank holds both a rule that needs
  unread input and one that does not, `rule_conflict`; then `text_not_read` when every top rule needs unread
  input; then `rule`. Measure the mixed rows first (expected 0); a dbt unit test with one mixed case and one
  all-unread case. Snapshot diff zero on the five funds.
- (d) **Guard on detail ceilings.** `pytests/test_detail_ceilings_have_tests.py`: for every key of
  `cmp_amount_detail_max` and `cmp_rate_detail_max` in `dbt_project.yml`, a test entry in `_intermediate.yml`
  with the same basis, field, cause and detail. Fails on a key without a test. Show it failing on a hand-made key
  in a temporary copy (do not commit the bad key).
- (e) **`printed_margin_cash_plus_pik`** is marked `built_in_slice` 4 in `seeds/reading_action.csv` while the
  spec says not built. Fix the label so the seed does not claim the effect is built, with zero rows moved. First
  read whether `int_field_rule` / `int_rate_normalised` decide `text_not_read` before `action_not_built`. If a
  label change would move rows from `text_not_read` to `action_not_built`, keep `built_in_slice` and correct the
  seed description and spec 6.4 instead. Say which.
- (f) **CI fixture row: a rate tag with no rate reading declared.** Smallest change that gives one fixture
  position a rate tag and no rate reading (for example a dated `reading_rules` entry that ends before one fixture
  filing, if the loader allows a dated rate reading; otherwise a second fixture fund). Expected:
  `interest_rate` unresolved, `rate_kind` `unresolved`, no value. Extend `tests/ci_fixture_expected_rates.sql`.
- (g) **Fund names in SQL comments**: remove from `int_filing_candidate.sql`, `int_role_structure.sql`,
  `models/marts/fact_fund_period.sql`, `tests/baseline_concept_rule_value_and_term.sql` (5 hits measured
  2026-11-24). Add `pytests/test_no_fund_names_in_sql.py`: no file under `models/`, `macros/`, `tests/`, `seeds/`
  names a fund of the five or writes one of their CIKs (diagnostic scripts under `scripts/` are exempt).
- **Nothing else moves.** Snapshot diff zero for every base table and the view, except the CI fixture rows named
  in (b) and (f).

**Tests to add:** the unit-kind seed tests (unique pattern match, every read unit covered); the tie-break unit
test; the two pytests.

**Proofs:** snapshot diff output (every table, counts); build totals; pytest count (146 plus the new ones); the CI
fixture run in an empty folder (`run_fixture_build.py --work <empty folder>`), all steps passing.

**Stop and report, do not decide, if:** the split moves any row; a unit text in the five funds' filings matches no
seed row and is not a filer unit; the tie-break change moves any row on the five funds; fixing (e) would move a
row; (f) needs a change to the loader or the parser.

**Done when:** (a) to (g) are each shown done, the diffs are zero, the build ends `ERROR=0`, and the work is
committed (one commit per item group is fine).

---

### Task 2: Inventory of correction stores, and the loader

**Files:**
- Create: `scripts/slice5/q_inventory_*.sql`, `seeds/correction_field.csv`, `docs/baseline_corrections_2026-11-24.md`
  (section 1, inventory), `pytests/test_readings_agent_stores.py`
- Modify (if decision 1 is yes): `readings_loader/cli.py`, `readings_loader/__init__.py` (version 6, new
  columns), a new module `readings_loader/agent_stores.py`, `load_readings.ps1` (only if arguments change),
  `models/staging/readings/stg_correction.sql`, `_readings_sources.yml`, `_readings_staging.yml`, a new view
  `stg_correction_rule.sql`, `stg_row_store_drift.sql` or a new drift view for the agent files,
  `dbt_project.yml` (vars), `ci/run_fixture_build.py`, `ci/fixture/` (one small agent store file of each kind)
- Modify: `intermediate_spine.md` section 11 (closes the open point "which correction stores")

**Interfaces:**
- Consumes: `data/overrides/` (read-only), `stg_correction`, `int_source_row`, `int_context_feature`,
  `stg_holdings` (for counts only).
- Produces:
  - `stg_correction` gains `kind` value `add_row` (one correction row per field of a `row_add` position, keyed
    by its `accession` and `src_context_id`, sharing an `add_group_id`) and rows from the B2 value leaf (keyed by
    the leaf's `row_id`, resolved in Task 3; new column `row_id`, null elsewhere). New columns: `row_id`,
    `add_group_id`, `source_file`. Loader version 6.
  - `stg_correction_rule`: one row per row-selecting rule of the agent stores (12 `row_exclusion`, the B2
    `comparative_period_filter`): cik, rule id, rule type, scope quarters, predicate text, evidence, file. Loaded
    for the record; no model applies it.
  - Seed `correction_field`: `correction_field`, `layer_field` (null when this layer does not hold the field),
    `step` (`filed`, `converted`, `reading_input`, `companion`, or `deferred`), `companion_of` (for a companion
    field: the field it travels with), `note` (the production code that applies it).

**Requirements:**
- **Inventory first, from the files, not from the docs.** Every store under `data/overrides/` with an entry for
  one of the five funds: per store, fund, quarter and field, the count, whether the loader loads it today, what it
  can do (set, withdraw, add a row, remove a row), and where production applies it (the table in "How production
  applies corrections" above is the starting point; verify each line). The measured starting counts are in the
  appendix; re-measure them. Write section 1 of `baseline_corrections_2026-11-24.md`.
- **Key shapes** (measured 2026-11-24): `row_corrections` 1,413, all keyed by identifier (no context);
  `row_corrections_by_context` 2,498, all with a context; wrapper entries 285, all with a context and no report
  date. State per store how a key becomes a target (Task 3 builds it).
- **Loader (decision 1).** If yes: load each `row_add` position's fields as `add_row` corrections and the B2
  `all_pik_normalization` leaf as `value` corrections (its `cash_rate`, `pik_rate`, `set_interest_to_cash`
  mapped to `interest_rate_cash`, `pik_rate`, `interest_rate_kind` per `pipeline/agent_b2_appliers.py`; read the
  applier and say exactly what it sets). Skip files whose name starts `_retired` or `_pulled`, or contains
  `.proposed.` or `.review.`, as `pipeline/rule_admission.py` `admitted` does. Unknown rule types or fix classes
  are a `LoadError`, never skipped. The loader records each file's text sha256 (CRLF read as LF,
  `store.text_sha256`) in the manifest, and a drift view fails the build when one changes after the load (ceiling
  0), as `stg_row_store_drift` does for the CSVs.
- **`correction_field` seed.** One row per field that occurs in the loaded stores (37 field names today, appendix
  table A3). Steps: `filed` for wrapper `untagged_values` fields (production fills them at parse time);
  `converted` for row-store amounts (`fair_value`, `cost`, `principal_amount`, `principal_amount_usd`,
  `shares_held` to `shares`, `pct_of_net_assets`) and `maturity_date`; `reading_input` for `interest_rate`,
  `pik_rate`, `basis_spread` to `spread`, `interest_rate_kind`, `interest_rate_cash`; `companion` for
  `principal_amount_currency`, `principal_fx_rate_to_usd`, `principal_fx_status`, `cost_currency`; `deferred` for
  every field this layer does not hold (names, industry, classes, reference rate text, coupon type, maturity
  precision, `identifier`). The store is part of the key where the step differs by store (untagged values are
  `filed`, the same field in a row store is `converted`): give the seed a `store_pattern` column.
- Verify, in production's code, whether `principal_amount_usd` is computed again after `_apply_row_corrections`
  (the stores set it explicitly on most rows: 108 + 96 corrections, with 107 + 95 FX-rate corrections beside
  them). The answer decides whether a corrected principal re-runs `to_usd` (`filed`) or not (`converted`). Name
  the file and line.
- Tests: `stg_correction` keys unique; every `kind` in its list; every loaded field has a `correction_field` row
  (test fails on a new field); every `add_row` group has a `fair_value` field.

**Proofs:** loader output (rows per table, corrections by store and kind); `pytest` count; snapshot diff: no table
other than the readings staging views changes; build totals.

**Stop and report if:** a store with entries for the five funds is found that is not in the table above; a store's
key cannot be mapped to (accession, context) without reading printed text; a `row_add` position has no
`src_context_id`; `pipeline/agent_b2_appliers.py` sets a field this layer does not hold; the loaded row counts
differ from the appendix by more than the entries added since 2026-11-24 (say which).

**Done when:** section 1 of the baseline file is written, the loader (if decided) loads and tests pass, the build
ends `ERROR=0`, and the work is committed.

---

### Task 3: Applying corrections to amounts and to the row set

**Files:**
- Create: `models/intermediate/int_correction_target.sql`, `int_correction_application.sql`,
  `int_row_corrected.sql`, `int_field_corrected.sql`; tests `tests/int_correction_*.sql`,
  `tests/baseline_int_correction_*.sql`; unit tests in `_intermediate.yml`; ceilings in `dbt_project.yml`
- Modify: `seeds/reading_action.csv` only if a new action is needed (state why), `_intermediate.yml`

**Interfaces:**
- Consumes: `stg_correction`, seed `correction_field`, `int_source_row`, `int_context_feature`
  (`identifier_label`), `int_field_read`, `int_amount_normalised`, `stg_holdings` (only for the
  `production_bridge` key resolution, decision 2, and the B2 `row_id`), `stg_fx_rate`.
- Produces:
  - `int_correction_target`: one row per (`correction_id`, target `accession`, `context_id`); a correction with
    no target has one row with null `context_id`. Columns: `correction_id`, `store`, `kind`, `cik`, `accession`,
    `context_id`, `field`, `layer_field`, `step`, `key_resolution` (`context`, `identifier_native`,
    `production_bridge`, `row_id`, `not_found`), `target_count` (targets of this correction),
    `target_role` (role in `int_source_row`), `report_date` (from `int_source_row` when the store has none).
  - `int_correction_application`: same grain. Columns: the target columns, `outcome` (`applied`, `no_op`,
    `rejected`, `failed`, `deferred`), `reason`, `value_before` (the normalised value, as text), `value_after`
    (the corrected value, as text), `applied_at_step`.
  - `int_row_corrected`: one row per (accession, context) that is a position after corrections: all positions of
    `int_source_row` plus contexts a correction makes positions. Columns: `accession`, `context_id`, `cik`,
    `report_date`, `role_filed` (from `int_source_row`), `role` (`position`), `is_published`, `scope`, `is_cash`,
    `row_correction_ids` (null for a filed position), `row_reason` (`filed`, `correction_supplies_fair_value`,
    `correction_supplies_term`, `correction_adds_row`).
  - `int_field_corrected`: one row per (accession, context, field) for every row of `int_row_corrected` and every
    field of `int_field_normalised`. Columns: `accession`, `context_id`, `field`, `cik`, `report_date`,
    `value_filed`, `value_normalised`, `value` (the corrected value), `currency_normalised`, `currency`,
    `value_date_normalised`, `value_date`, `rate_kind_normalised`, `rate_kind`, `action`, `rule_id`, `status`
    (`normalised`, `corrected`, `withdrawn`, `absent`, `unresolved`), `reason`, `correction_id`. This task fills
    the amount fields; rate fields are carried through unchanged until Task 4.

**Requirements:**
- **Key resolution**, in this order: a context id as given; else the B2 `row_id` through production's row
  (`stg_holdings.row_id`, same accession); else identifier text equal to `int_context_feature.identifier_label` on
  a position of the same accession (`identifier_native`); else, if decision 2 is yes, production's row with the
  same accession and `bdc_investment_identifier` (`production_bridge`); else `not_found`. An identifier matching
  several positions applies to each (as production does), with `target_count` beside it. Measured 2026-11-24:
  identifier keys resolve natively to one position 1,343 times, to several 3 times, to none 67 times (bridge finds
  production's row for all 67).
- **Outcomes** (one per target):
  - `deferred`: `correction_field.step = 'deferred'`, and kinds `relabel` (identifier text). Expected about 2,375.
  - `no_op`, reason `evidence_only` (kind `evidence`); `procedure_not_built` (kind `exception`, until the HPS
    procedure exists); `equal_to_normalised` (the corrected value equals the normalised value within the field's
    tolerance from `cmp_amount_tolerance`); `already_absent` (a withdrawal on an absent field).
  - `rejected`, reason `target_not_found`; `target_not_position` (the context exists and is not a position, and
    the correction does not supply what its role lacked, see the row rule below); `conflict` (two corrections set
    the same field of the same target to different values; neither applies; 0 today, ceiling 0, decision 7);
    `expected_value_differs` (a relabel whose expected label is not the context's label; measured, not applied).
  - `failed`, reason `value_not_numeric`, `value_not_date`, `unit_not_known`, `no_fx_rate`.
  - `applied` otherwise.
- **Row rule** (mirrors `cmp_row_set`'s `needs_correction` rule, which is the measured evidence): a context
  becomes a position when (i) its role is `not_schedule` by rule 3 (no fair-value fact) and an applied correction
  supplies `fair_value`, or (ii) its role is `unresolved` by rule 7 or 9 for want of a term fact (not
  `held_for_two_scopes`) and an applied correction supplies a term field (`principal_amount`, `shares_held`,
  `interest_rate`, `basis_spread`, `pik_rate`, `maturity_date`), or (iii) it is an `add_row` group. Its scope is
  `fund` unless a scope rule in `int_source_row` already names one; its `is_published` follows the existing rule
  (`position` and scope `fund`). Measured 2026-11-24: (i) 44 Apollo contexts (wrapper `untagged_values`, fair
  value 0), (ii) 8 contexts (Ares 2 at 2022-09-30, Apollo 6), together the 52 published `needs_correction` rows
  of `cmp_row_set`; (iii) the 8 Ares `row_add` positions if decision 1 is yes. Any other promotion fails the build
  (ceiling per reason, set to the measured count).
- **Apollo zero-value lines** (owner decision 2026-11-23; decision 4 above): published at 0 through rule (i).
  12 of the 44 sit under the two rollups (Chemicals Heubach, Media Material+). The rollups stay aggregates: no
  role in `int_source_row` changes. Report, per quarter, the rollup's fair value and cost against the sum of the
  rows beneath after the zero lines are added.
- **Values.** Step `filed`: the corrected value replaces `value_filed` and the field's conversion runs on it (a
  foreign principal with a currency in `value_unit` converts with `to_usd`; the two Apollo EUR / GBP principals,
  `not_yet_explained|correction_loaded_value_not_matched` today, are the test case). Step `converted`: the
  corrected value replaces the converted value; derived fields follow only as production derives them after its
  correction step (Task 2's finding on `principal_amount_usd`). A withdrawal (empty value) gives `status
  'withdrawn'`, `value` null; `value_normalised` keeps the old value. A companion field travels with its field
  (currency with principal; FX rate and status with dollar principal; cost currency with cost); a companion with
  no corrected main field on the row is applied to the companion column where this layer has one
  (`principal_amount` row's `currency`), else `deferred`.
- **Never erase.** `value_filed` and `value_normalised` are always present beside `value`; a test fails if any row
  has `status = 'corrected'` and a null `correction_id`, or a `correction_id` with `status` not in
  (`corrected`, `withdrawn`).
- Tests: keys unique on all four models; every correction appears in `int_correction_application` at least once
  (no correction dropped); every `applied` row names a field `int_field_corrected` holds and changes it; outcome
  and reason in their lists; unit tests for each outcome on hand-made rows (one applied, one no-op, one rejected
  per reason, one failed, one deferred, one promotion per row rule, one that must NOT promote: a correction of
  cost on a `not_schedule` context). Baseline tests with ceilings: count per outcome and reason; promotions per
  row reason; `production_bridge` resolutions (67 if decision 2); identifier keys with `target_count > 1` (3).
- Sum check: run `sum_not_tied_rows` on the corrected published basis as a new test, its pinned list measured
  (today 11 fund-quarters do not tie on the normalised basis; Ares and Apollo quarters with rows added by
  corrections may now tie). The normalised-basis test stays as it is.

**Proofs:** outcome table per store, fund and field; promotions per fund and quarter; snapshot diff: no existing
table changes except `stg_*` views untouched, new models added; every fair value that differs between
`value_normalised` and `value` listed (expected: 2 Apollo row-store fair values, 44 zero fills on promoted rows, 8
Ares rows if loaded); build totals.

**Stop and report if:** a correction would change a published fair value, cost or principal outside the measured
groups above; rejected outcomes other than `target_not_found` exceed 0, or `target_not_found` exceeds 67 (0 if
decision 2 is yes and the bridge works); a promotion happens on a context whose role rule is not 3, 7 or 9; any
`conflict`; the row rule promotes a context that production does not publish.

**Done when:** every correction has an outcome, the four models build with their tests, the ceilings are set to the
measured counts, the build ends `ERROR=0`, and the work is committed.

---

### Task 4: Corrections on rates, and the two wrapper procedures

**Files:**
- Create: `models/intermediate/int_rate_corrected_input.sql` (or a CTE block inside `int_field_corrected`; say
  which and why), `int_rate_adjacent.sql`; tests; unit tests; ceilings
- Modify: `int_field_corrected.sql`, `int_rate_normalised.sql` (only to read `int_rate_adjacent`),
  `seeds/reading_action.csv` and `seeds/action_field.csv` (action `adopt_adjacent_rate_context`, if built),
  `readings_loader/wrappers.py` (move `rate_only_contexts adopt_adjacent` from not-loaded to a rule) with pytests,
  `warehouse/wrappers/0001287750.json` only if the rule needs a `reading_rules` entry with evidence

**Interfaces:**
- Consumes: `int_correction_application` (rate corrections), `int_rate_normalised` inputs, macro `rate_reading`
  (Task 1), `int_field_read`, `int_context_feature`, `stg_reading_rule`.
- Produces: rate rows of `int_field_corrected` (`interest_rate`, `interest_rate_cash`, `pik_rate`, `spread`,
  `maturity_date`, and `rate_kind` on the `interest_rate` row) on corrected inputs; `int_rate_adjacent`: one row
  per taker context with the giver context, the moved facts and the rule id.

**Requirements:**
- **Rate corrections are reading inputs** (production applies them before `financial_finalization.prepare_artifact`
  derives the legs and kind; read `pipeline/financial_finalization.py` and `pipeline/financial_conventions.py`
  `prepare` and name the lines). A corrected `interest_rate`, `pik_rate`, `interest_rate_kind` (`cash` or
  `all_in`) or `interest_rate_cash` replaces the corresponding input; `rate_reading` runs again on the corrected
  inputs; the corrected all-in rate, cash leg and kind are its output. An explicit corrected kind decides the
  reading on its row (production reads an explicit kind before any tag or fund rule, `unified_holdings.py`
  lines 2236-2240). State what rule id a row read under a corrected kind names (the correction's id, with the
  action of the kind it states).
- Corrections on `basis_spread` and `maturity_date` replace the converted spread and date (`converted`); a
  withdrawal empties them.
- The legs check (cash plus PIK equals all-in) runs on corrected rows too; a corrected row that fails it is
  `failed`, `legs_do_not_add`, never stored. Measured 2026-11-24: of the 454 published rate `needs_correction`
  rows, a same-field correction carries production's value on rate 48 of 51, PIK 158 of 158, spread 123 of 123,
  maturity 9 of 9; cash leg 0 of 68 and kind 15 of 45 depend on the re-run reading. Report the counts after.
- **Ares `adopt_adjacent`** (decision 5): the rule in `pipeline/source_encodings.py` `adopt_rate_only_contexts`
  (lines 689-748) uses structure only: within one filing and period, a context with rate facts and no fair value,
  cost or principal (giver) and a context with fair value and principal and no rate facts (taker); context numbers
  differing by one; the same first 16 letters and digits of the identifier (lowercased, non-alphanumerics removed,
  at least 8 characters); one candidate on each side under that key. The taker takes the giver's rate, spread and
  PIK facts. Build it as a reading rule (`rule_class` convention, target `interest_rate`, the new action), selected
  by the fund's wrapper declaration, never a list of contexts. The giver is already `not_schedule` here (rule 3);
  it stays so. Expected (slice 4 Task 3 approximation): 7 pairs (2023-12-31 1, 2025-03-31 1, 2025-06-30 3,
  2025-09-30 2); production names moved fields on 6 published rows; `cmp_row_set` has 2 new-only and 2
  production-only `rate_only_context_pair` rows. Explain each of the 7 against those.
- **HPS whole-coupon PIK** (decision 5): not built. It needs (1) the printed row's text parsed with the coupon
  grammar of `pipeline/whole_coupon_pik.py` `parse` (benchmark, margin, PIK, coupon), and (2) production's loan
  class (`asset_category = 'LOAN'`, `eligible`), a text class this layer does not hold (D17). The filed layer holds
  the printed cells, but no model reads them as a grammar, and D2 puts text fields in the second spec. The 44
  published cash-leg and 44 PIK-rate differences (`needs_store_not_loaded|whole_coupon_pik_not_read`) stay, as do
  the 3 HPS rows of controller ruling R2. The 3 wrapper "not" entries stay `no_op`, `procedure_not_built`.
- Tests: unit tests for a corrected rate under each kind, a corrected PIK rate that changes the cash leg, a
  corrected kind `cash`, a withdrawal, and one corrected row that must fail the legs check; `adopt_adjacent` unit
  tests with one pair taken and three refused (ordinals two apart; two candidates under one key; identifier key
  under 8 characters). Ceilings: rate outcomes per reason; adopted pairs (7 or the measured count).

**Proofs:** counts per field of corrected, withdrawn, failed rate rows; the 7 pairs with their printed rows (open at
least 3); snapshot diff: amount rows of `int_field_corrected` and every table except the rate rows of
`int_field_corrected` and `int_rate_adjacent`/`int_rate_normalised` (the taker rows only) unchanged; build totals.

**Stop and report if:** the re-run reading gives a cash leg or kind that differs from production's on more than 10
corrected rows and no production rule explains it; `adopt_adjacent` matches a pair outside Ares or more than the
measured pairs; the rule needs printed text; a corrected rate fails the legs check on more than 0 rows.

**Done when:** rate rows of `int_field_corrected` are built on corrected inputs, `adopt_adjacent` is built or
reported as not buildable with the reason, the build ends `ERROR=0`, and the work is committed.

---

### Task 5: Comparison again, and the BCRED trace

**Files:**
- Modify: `models/intermediate/cmp_row_set.sql`, `cmp_amount.sql`, `cmp_rate.sql`, `_intermediate.yml`,
  `dbt_project.yml` (ceilings, detail ceilings)
- Create: `scripts/slice5/q_t5_*.sql`; section 2 of `docs/baseline_corrections_2026-11-24.md`

**Interfaces:**
- Consumes: `int_row_corrected`, `int_field_corrected`, `int_correction_application`, `stg_holdings`.
- Produces: the three comparison models with the same columns as today, plus `correction_id` and
  `value_normalised` beside `value_new` (amounts and rates).

**Requirements:**
- `cmp_row_set` compares `int_row_corrected` (published basis: `is_published`) with production. `cmp_amount` and
  `cmp_rate` read `int_field_corrected` in place of `int_field_normalised`.
- Every former `needs_correction` row becomes `equal`, or gets a cause from the closed list with a new detail
  that names the mechanism, never `needs_correction` with the old detail. Expected new details include
  `correction_applied_value_differs` (a correction applied and production holds another value: open every such
  row before naming its cause) and `correction_rejected_<reason>` / `correction_deferred` (production applied a
  correction this layer did not). `not_yet_explained` and `new_wrong` stay 0 on every field and basis; a row that
  cannot be explained goes to `not_yet_explained` with its own detail and ceiling and is reported, never hidden.
- Starting counts (2026-11-24): `cmp_amount` published `needs_correction`: fair value 2, cost 14, principal 5,
  currency 282, dollar principal 194, shares 219 (716). `cmp_rate` published: rate 51, cash 68, PIK 158, spread
  123, maturity 9, kind 45 (454); unpublished: spread 142, maturity 2 (144). `cmp_row_set` published 52
  (production only: 44 not_schedule, 8 unresolved). Report the same table after, per field, basis and new cause.
- The detail `not_yet_explained|correction_loaded_value_not_matched` (2 Apollo dollar principals) should become
  equal through `to_usd` on a corrected foreign principal; if not, say why.
- `needs_store_not_loaded|production_row_added` (8 Ares rows) and `needs_correction` on the B2 row become equal if
  decision 1 is yes. `needs_store_not_loaded|rate_only_context_pair` (4) and `rate_only_context_not_adopted`
  (rate 6, cash 1, PIK 2, spread 4, kind 6) should become equal through Task 4.
- **BCRED trace** (owner decision 2026-11-23), time limit 60 minutes of work, logged in the ledger with start and
  end. The 14 rows: `cmp_amount` principal and dollar principal `not_yet_explained|principal_empty_class_not_equity`
  (BCRED 2025-06-30 to 2026-06-30; production class STRUCTURED_CREDIT, `asset_category` EQUITY_COMMON, no
  correction). Leads, in order: `pipeline/printed_sections.py` `apply_structured_sections` (lines 113-162: sets
  EQUITY_COMMON on equity tranches); the principal emptying by class in `pipeline/unified_holdings.py` (lines
  1346-1360) and whether it runs on `asset_category`; `pipeline/financial_finalization.py`. Found: name the file,
  line and condition, and give the rows the cause the evidence supports (stop for a controller ruling between
  `old_wrong`, `convention` and `owner_review`). Not found in the time: cause `old_wrong`, detail
  `production_empties_principal_step_not_found`, ceiling 14 each, and the leads tried in the baseline file.
- Ceilings set to the measured counts; old `needs_correction` ceilings lowered to what remains (0 expected on
  most fields).

**Proofs:** before/after tables per field, basis and cause; every new detail with the rows opened (at least 3 per
detail, or all if fewer); snapshot diff: no `int_*` table changes in this task; build totals.

**Stop and report if:** any row becomes `new_wrong`; `not_yet_explained` rises on any field; a published fair value,
cost or principal differs from production on a row that was equal before this slice; the trace runs past 60
minutes.

**Done when:** no row carries the old `needs_correction` details, every new cause has evidence and a ceiling, the
build ends `ERROR=0`, and the work is committed.

---

### Task 6: Measurements for consolidation, CI fixture, records

**Files:**
- Create: `scripts/slice5/q_t6_pinned_reusable.sql`, `scripts/slice5/q_t6_repeats.sql`;
  `tests/ci_fixture_expected_corrections.sql`
- Modify: `docs/baseline_corrections_2026-11-24.md` (sections 3 and 4), `ci/fixture/` (row stores, wrapper,
  agent store files), `ci/run_fixture_build.py` (selection, if new models need it), `ci/README.md`,
  `warehouse/README.md`, `warehouse/docs/HANDOFF.md`, `warehouse/docs/intermediate_spine.md` (status line, 6.5
  "as built", section 11, decisions added), `docs/agent_changelog.md` (append one entry; touch nothing else)

**Interfaces:**
- Consumes: everything above.

**Requirements:**
- **Consolidation measurements** (owner request; measure only, change nothing). For the five funds:
  - (a) Pinned versus reusable, per fund, store and field. Pinned: the correction names one filing (accession) and
    one row (context, identifier or row id). Reusable: it names no row: a filer-level rule (all quarters) or a
    dated rule (a quarter range or a quarter, selecting rows by a condition). Measured 2026-11-24: all 4,196
    loaded corrections are pinned. Of the 14 live agent rules: 6 are reusable for all quarters (BCRED 2, Blue
    Owl 2, Ares 1, Apollo 1); 1 is a dated condition (Blue Owl 2025-12-31); 5 exclusions name rows (Ares
    2025-09-30 by row ids, Ares 2023-06-30 and 2024-03-31 by one member text each, Blue Owl 2026-03-31 by a
    context list, Apollo 2023-09-30 by one identifier); the 2 `row_add` rules list positions (pinned). B2: the
    comparative filter is a dated condition (one quarter), the PIK fix names one row. Re-measure.
  - (b) Repeats: row-pinned corrections that make the same fix to the same position in more than one quarter.
    "Same position": production's `position_id` of the target row (one build; ids are not stable across builds,
    AGENTS.md), and as a second measure the same fund and identifier text. "Same fix": same field and the same
    value (text trimmed; empty means withdraw; numbers equal within the field's tolerance). Count per fund, store
    and field: position-fields corrected in 2+ quarters, those with the same fix in 2+ quarters, and the
    corrections inside such repeats. Measured 2026-11-24 (by position id, all value corrections): Ares 67
    position-fields / 165 corrections, BCRED 152 / 344, Blue Owl 40 / 106, Apollo 159 / 447, HPS 155 / 645;
    1,707 of 3,975 value corrections sit in a repeat.
  - State what the definitions miss: a fix whose value changes each quarter because the underlying amount moves
    (a corrected principal, a rate reset) is not "the same fix" though the mechanism is; a position whose id
    changes between quarters (matching breaks, a relabel) splits one repeat into two; identifier text that changes
    between quarters hides a repeat on the second measure; a correction keyed by identifier that hits several rows
    counts once per position; the measure says nothing about whether a reusable rule could replace the repeat
    (that is the later exercise).
  - Write these as section 3 of the baseline file, dated, with the queries named.
- **CI fixture:** at least one correction of each outcome on fixture rows: applied (the existing cost 990 on c-3),
  `no_op`, `rejected` `target_not_found`, `deferred` (the existing issuer name on c-4), one `untagged_values` fair
  value that promotes a context, one rate correction whose cash leg is derived again, and (if decision 1) one
  `row_add`. Extend `tests/ci_fixture_expected_corrections.sql`. Prove the fixture commands locally in an empty
  folder.
- **README:** a short section, "Corrections: what is applied and what is recorded", in the plain style of the
  existing sections and in dbt terms a newcomer can follow: where corrections come from, the five outcomes, why a
  correction never erases a filed value, and why applying production's corrections is agreement, not proof.
- **HANDOFF:** a dated section "State after slice 5" with the counts, the outcome table, the open owner decisions,
  the rulings made without the owner (each with its cost if wrong), what is left for slice 6 (`int_observation`,
  findings, the first-run review list) and the deferred items. Update the "RESUME HERE" pointer. Note that the
  "short branches off `main`" plan line is superseded by AGENTS.md (trunk `dev`).
- **Spine:** status line; 6.5 as built (keys, steps, outcomes, the row rule); section 11 open point closed with the
  store list; the owner decisions taken before this slice as D20 onward.
- **Changelog entry:** what was added, the counts, build result, Python test count, CI fixture result, and the
  sentence that a passing build and agreement with production are not statements that the data is correct.

**Proofs:** CI fixture run output (each step's totals); build totals; pytest count; the baseline file sections.

**Stop and report if:** the CI fixture needs a model change to pass; a measurement in (a) or (b) disagrees with the
appendix by more than the entries added since 2026-11-24 without an explanation.

**Done when:** the baseline file has its four sections, the fixture passes locally, the records are written, the
build ends `ERROR=0`, and the work is committed. Nothing is pushed: a push needs the owner's go.

---

## Contradictions found while writing this plan

| Where | What it says | What was measured or read |
|---|---|---|
| `HANDOFF.md`, "Next: slice 5" | 520 published rate field rows wait on corrections | 454 published (and 144 unpublished). The 520 predates controller ruling R1 (64 cash legs moved to `printed_pik_not_read`) and ruling B (2 rows now equal) |
| `HANDOFF.md`, "Plan after this slice" | Short branches off `main` after a catch-up merge | Superseded: `dev` is the trunk, `main` the published branch (AGENTS.md, 2026-11-24) |
| `HANDOFF.md`, first line | "Current state: read State after slice 3" | "State after slice 4" exists further down |
| `intermediate_spine.md` section 5 | "The 284 row-level entries go to the corrections table" | 285 wrapper-derived corrections load today (64 values, 202 relabels, 3 exceptions, 16 evidence) |
| `intermediate_spine.md` 6.5 | A correction whose filed value is not what it expected is reported and not applied | The row stores carry no expected value (columns: cik, report date, accession, identifier, field, value, reason, evidence, author, date, context). Only the 202 relabels carry one |
| `intermediate_spine.md` section 4 | Corrections loaded "from the wrappers' row-level entries and the existing correction stores for the five funds" | Only the two CSV stores and the wrappers are loaded; the two agent stores are not |
| `design.md` section 1 | About 20 correction stores | For the five funds four families change holdings (two CSVs, wrapper entries, two agent stores); `bdc_aggregate_row_overrides.json` has 7 Ares entries but only a check reads it |
| `design.md` section 4 | `correction_application` outcomes: applied, no-op, rejected, failed | 2,375 corrections touch fields this layer does not hold; decision 3 proposes `deferred` |
| `seeds/reading_action.csv` vs spine 6.4 | `printed_margin_cash_plus_pik` built in slice 4 | Spine: not built (`unread_input`; rows `text_not_read`). Task 1 (e) |
| `stg_correction` | `report_date` | Null on every wrapper-derived correction (the wrapper entries carry no date); Task 3 takes it from the target row |

## Assumptions not verified

- Whether production computes `principal_amount_usd` again after its row corrections (Task 2 verifies). The
  stores set it explicitly on most corrected rows, which suggests not.
- That the 67 identifier keys with no native match are the same rows production's identifier names (the bridge
  finds one production row for each; for 63 of them that row is a position here; the label difference was read
  on 12 Blue Owl examples, not on HPS rows).
- That the 32 Apollo zero-value lines outside the two rollups print a dash (not opened in print while writing).
- That `adopt_adjacent` gives the same 7 pairs on this layer's contexts as production's on its frame (slice 4's
  approximation; production names 6 rows).
- That `position_id` links quarters within one production build for the repeat measure (true by design of the
  matcher; not checked here).
- Whether the B2 leaf's `row_id` (`ROW-62c19264d44492af`) is still a row of production's holdings: its own
  rationale cites another row id (`ROW-d9cfbfcb882d5425`); production's audit says it applied to 1 row.

## Appendix: measurements behind this plan (2026-11-24, HEAD 7eac03c0, full rebuild `PASS=690 WARN=106 ERROR=0 TOTAL=796`)

Queries were run with `warehouse/scripts/slice2/run_sql.py` from the OS temp folder; Task 2 re-creates them under
`warehouse/scripts/slice5/`.

**A1. Loaded corrections per store, fund and kind** (`stg_correction`).

| Store | Ares | BCRED | Blue Owl | Apollo | HPS | Total |
|---|---:|---:|---:|---:|---:|---:|
| row_corrections (value, identifier key) | 195 | 18 | 171 | 852 | 177 | 1,413 |
| row_corrections_by_context (value, context key) | 186 | 1,132 | 211 | 273 | 696 | 2,498 |
| wrapper untagged_values (value) | 6 | 1 | 0 | 57 | 0 | 64 |
| wrapper relabelled_contexts (relabel) | 0 | 0 | 202 | 0 | 0 | 202 |
| wrapper pik_margin_reading (exception) | 0 | 0 | 0 | 0 | 3 | 3 |
| wrapper rate_verification_anchors (evidence) | 16 | 0 | 0 | 0 | 0 | 16 |
| Total | 403 | 1,151 | 584 | 1,182 | 876 | 4,196 |

Quarters covered: row stores 2022-09-30 to 2026-06-30 (per fund 6 to 16 quarters); wrapper entries carry no date.

**A2. Not loaded, with entries for the five funds.**

| Store | Fund | Entries | Effect | Applied in production's last build (audit 2026-11-16) |
|---|---|---|---|---|
| agent_investigate_rules | BCRED | 2 row_exclusion (all quarters) | remove rows | 65 and 2 rows |
| agent_investigate_rules | Blue Owl | 4 row_exclusion (2 all quarters, 2 dated) | remove rows | 13, 11, 69, 1 rows |
| agent_investigate_rules | Ares | 4 row_exclusion, 2 row_add (8 positions) | remove rows; add rows | 2, 82, 0 (noop), 1; 4 + 4 added |
| agent_investigate_rules | Apollo | 2 row_exclusion | remove rows | 1, 1 rows |
| agent_b2_corrections | Ares | all_pik_normalization (1 row), comparative_period_filter (2025-12-31) | set rate fields; remove comparative rows | 1 row; 1,348 rows |

`_retired*`, `_pulled*` and `.review.` files are not counted. HPS has no live agent rule.

**A3. Value corrections by field family.** Spine numeric 1,022 (row_corrections 578, by context 380, wrapper 64);
companion 780 (415, 365, 0); not held by this layer 2,173 (420, 1,753, 0). Largest fields: `reference_rate_type`
and `reference_rate_source` (399 each), `issuer_name` 401, `basis_spread` 269, `shares_held` 229,
`principal_amount_currency` 329, `extracted_industry` 328, `instrument_description` 212, `pik_rate` 163.
Withdrawals (empty value): 563, mostly reference-rate text and BCRED/HPS spreads (143 context-keyed spreads).

**A4. Key resolution.** Context keys: 2,498 row-store corrections, of which 2,488 on positions, 8 on unresolved
contexts, 2 on `not_schedule` contexts. Wrapper values: 5 on positions, 44 on `not_schedule` (rule 3), 15 on
unresolved contexts. Identifier keys (1,413): native match to one position 1,343, several 3, none 67 (Blue Owl
21 and HPS 42 on positions here where production's identifier drops the member's last segment; Ares 6 and Apollo
1 on contexts unresolved here). Production's row by accession and identifier: exactly one for 1,407, several for 6,
none for 0.

**A5. Collisions.** Same accession, key and field: 0 conflicts, 0 repeats. After key resolution (context, native,
bridge): 0 conflicts, 0 repeats.

**A6. Context-keyed spine corrections on positions against today's converted value.** Changes 135, fills an empty
field 91, withdraws a value 143, equal already 10, withdraws an absent value 1.

**A7. `needs_correction` today** (published unless stated).

| Model | Field | Rows | Same-field correction carries production's value |
|---|---|---:|---:|
| cmp_amount | fair_value | 2 | 2 |
| cmp_amount | cost | 14 | 14 |
| cmp_amount | principal_amount | 5 | 5 |
| cmp_amount | principal_amount_currency | 282 | 280 |
| cmp_amount | principal_amount_usd | 194 | 192 |
| cmp_amount | shares | 219 | 219 |
| cmp_rate | interest_rate | 51 | 48 |
| cmp_rate | interest_rate_cash | 68 | 0 (derived) |
| cmp_rate | pik_rate | 158 | 158 |
| cmp_rate | spread | 123 | 123 |
| cmp_rate | maturity_date | 9 | 9 |
| cmp_rate | rate_kind | 45 | 15 (derived) |
| cmp_rate, unpublished | spread | 142 | 142 |
| cmp_rate, unpublished | maturity_date | 2 | 2 |
| cmp_row_set | production-only rows | 52 | 44 Apollo zero fair values (wrapper), 8 term values (Ares 2, Apollo 6) |

**A8. Units in the five funds' filings** (`stg_filed_unit`): `iso4217:USD`, `pure`, `utr:Rate`,
`iso4217:USD/shares`, `shares`, 17 other currency codes (including `iso4217:KPW`, 1 fact), and 30 other units
(29 filer units such as `arcc:borrower`, `hps:loan`, plus `utr:Q`): 52 unit texts. None written with the `xbrli:`
prefix.

**A9. The 14 BCRED principals** (`cmp_amount` `principal_empty_class_not_equity`): accessions
0001803498-25-000062, -25-000081, -26-000014, -26-000031, -26-000048; production index class STRUCTURED_CREDIT,
asset category EQUITY_COMMON, no correction, no unit count published.

## Self-review (2026-11-24)

- Scope A to G of the request: A in Task 1; B in Task 2 and appendix A1 to A5; C in Tasks 3 and 4; D in Task 5
  with the starting counts in A7; E1 in Task 3, E2 in Task 5, E3 in Task 4 (adopt_adjacent buildable from
  structure; whole-coupon needs printed text and a text class, so it stays a named difference); F in Task 6 with
  starting numbers; G in every task's proofs and Task 6.
- Spec coverage: 6.5 corrections (Tasks 3, 4); section 7 "a correction that did not apply" is recorded per
  correction now and becomes a finding in slice 6; section 11 open point closed (Task 2). Not in this slice:
  `int_observation`, findings, text fields, section 10.
- Names used consistently: `int_correction_target`, `int_correction_application`, `int_row_corrected`,
  `int_field_corrected`, `int_amount_normalised`, `int_rate_normalised`, `int_rate_adjacent`, seeds `unit_kind`,
  `correction_field`, macro `rate_reading`, outcomes `applied`, `no_op`, `rejected`, `failed`, `deferred`.
- Risk carried: the plan relies on production's code reading in two places (principal dollar re-derivation, rate
  reading order); both are stated as requirements to verify, with stop conditions.
