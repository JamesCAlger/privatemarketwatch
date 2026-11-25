# Handoff: data-model redesign in `warehouse/`

**Current state: read "RESUME HERE" and "State after slice 5 (corrections), 2026-11-25" near the end. The sections before them are history.**

Written 2026-11-18 at the end of the session that built steps 1 and 2. Read this first, then the documents it points to.

## State

- **Nothing is committed.** Branch `ensemble-fp-experiment`. The whole of `warehouse/` is untracked. `docs/agent_changelog.md` is modified: it holds two entries from this work (step 1 marts, step 2 filed layer) and uncommitted entries from other agents.
- No process and no subagent was left running (checked at shutdown).
- The rest of the repository was not changed by this work: `data/output`, `frontend/public/data`, `pipeline`, `scripts`, `tests`.

## What is built

| Step | What | Where |
|---|---|---|
| 1 | dbt marts over today's pipeline outputs, five v0.5 funds, position level only | `models/staging/`, `models/marts/`; spec `docs/design.md`, columns `docs/marts_columns.md`, baseline `docs/baseline_2026-11-18.md` |
| 2 | Parse-once filed layer: each cached filing parsed into nine Parquet tables | parser `filed_parser/` (version 3), output `data/filed/` (git-ignored), views `models/staging/filed/`; spec `docs/filed_layer.md`, baseline `docs/baseline_filed_2026-11-18.md` |

Step 3, the middle layer (source rows with a role, observations, corrections), is **not started and not requested**. It is the first step that needs per-filer judgement. Agree the design with the owner before building.

## How to run

All from the repository root, in PowerShell.

- `.\warehouse\dbt.ps1 build` : last result `PASS=162 WARN=11 ERROR=0 TOTAL=173`. The 11 warnings are baseline tests: they warn above zero and fail above the ceiling in `dbt_project.yml` (`baseline_max`).
- `.\warehouse\parse.ps1` : parses filings not yet parsed. `--verify` re-parses and compares hashes (last result 86 of 86, about 5 minutes). `--reparse` overwrites. One run at a time: two runs interfere.
- `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q` : 67 parser tests.
- Python is `warehouse\.venv` only. Never `pip install` into the shared `python` on PATH.

Passing tests show the layers are consistent and repeatable. They do not show the data is correct.

## Owner decisions waiting

1. DONE 2026-11-19: `warehouse/` committed (8be2e525).
2. DONE 2026-11-19: cash rows tagged (`is_cash`), reconciliation on the filed basis; `published_equals_filed` 11 to 0. Build now PASS=166 WARN=10 ERROR=0.
3. Whether to start the middle layer, and its design.
4. Whether the findings ledger moves onto dbt. Discussed, no decision.

## Not examined

- 46 holdings rows whose fair value matches no filed fact on their context (Apollo 44, Ares 2).
- 12 parsed filings with no holdings rows.
- 55 groups of contexts in one filing with identical members and period (BCRED 30, Ares 13, HPS 9, Apollo 3).
- 320 of the 896 position facts that sit in no printed table row.
- Whether a fact sits in the right cell: checked on two whole filings (BCRED, Ares), not all 86.
- Row spans: checked on a test fixture only.

## Rulings made without the owner

Listed with the cost of each in `docs/filed_layer.md` section 7 and in the step 2 ledger. The owner said they were reviewing in parallel and has not yet confirmed them.

## Parked minor defects (step 2 ledger has all fourteen)

- Two parse runs at once interfere (shared staging folder is swept at start).
- A missing table file whose manifest count is 0 goes unnoticed.
- The content hash does not distinguish a null from the literal text `\N`, and does not escape its separators.
- The fallback HTML parser is tested on a fixture only; no real filing used it.

## Where the detail is

- Ledgers, task reports and reviews: `.superpowers/sdd/2026-11-18-step1-marts-plan/` and `.superpowers/sdd/2026-11-18-step2-filed-layer-plan/` (`progress.md` first). Git-ignored.
- Agreed model and every owner decision: `scratch/2026-11-18_data_model/models.md` and `design.md` (scratch is disposable; `docs/design.md` here is the kept copy of the design).
- Diagnostic scripts left by agents: `warehouse/scripts/` (`diag_*`, `finalreview_*`, `fixround_query.py`, `measure_inline.py`, `count_concept.py`). Safe to delete; `make_manager_brand_seed.py` builds a seed and should stay.

## Standing rules that bit during this work

- No inline Python (`python -`, `python -c`). Two subagents sent a bare `python -` by mistake and had to be stopped. Say it explicitly in every dispatch.
- Subagents on Sonnet or Opus only.
- The owner is learning dbt: explain dbt terms in plain words.

## State after slice 2, 2026-11-19 (supersedes the State and step 3 lines above)

Passing tests and agreement with production show the layers are consistent and agree with the old
pipeline where stated. They do not show the data is correct.

### What is built

| Piece | What | Commits |
|---|---|---|
| Steps 1 and 2 | marts over today's outputs; the parse-once filed layer | 8be2e525, cash 9cb9bb44 |
| Spine spec | `docs/intermediate_spine.md`, owner decisions D1 to D15 | 4c02761e, 8de13bc0, 6e05d33c |
| Slice 1 | readings loader and rule table (`readings_loader/`, `load_readings.ps1`) | 7d32cc7a |
| Slice 2 | filing selection, row roles, comparison with production's row set; fund rules in the wrapper copies; CI fixture build | ff36e0c8 to 0292db6f, then the Task 4 commit that adds `ci/` |

Slice 2 models (`models/intermediate/`): `int_context_feature`, `int_filing_candidate`,
`int_filing_selected`, `int_role_structure` (rules 0 to 3), `int_role_text` (4, 5), `int_role_subtotal`
(6), `int_role_scope` (7), `int_role_fund_position` (fund rule releases), `int_source_row` (the role of
every context), `cmp_row_set` and `cmp_excluded_quarter` (the comparison). Plan
`docs/2026-11-19-slice2-row-roles-plan.md`; counts and causes `docs/baseline_roles_2026-11-19.md`; the
133 rows released by fund rules `docs/owner_review_rows_2026-11-19.csv`; ledger and task reports
`.superpowers/sdd/2026-11-19-slice2-row-roles-plan/` (git-ignored).

Where rules live (D10): fund rules in the new pipeline's wrapper copies `warehouse/wrappers/<cik>.json`
(taken byte for byte from `data/overrides/bdc_xbrl_wrappers/`; production's wrappers and schema
unchanged; `baseline_production_wrapper_changed` fails the build when a production wrapper changes);
general rules in `seeds/role_pattern.csv`. The seed `filer_concept.csv` and the sidecar idea are gone.

Pushed 2026-11-22 at ab299286. First CI run (45015590307): the `warehouse` job PASSED. The other two
jobs failed for reasons outside `warehouse/`, both failing since before this work: `frontend-build`
(`npm ci`: package-lock.json out of sync, missing react-is@16.13.1) and `python-tests` (collection
errors: `scripts.build_jev_bundles` not in the repo, `psutil` not installed in CI). Not fixed.

Slice 3 plan: `docs/2026-11-22-slice3-amounts-plan.md` (written 2026-11-22, not started, uncommitted).

### How to run

From the repository root, in PowerShell.

- `.\warehouse\parse.ps1` then `.\warehouse\load_readings.ps1` then `.\warehouse\dbt.ps1 build`. Last
  result (final fix wave) `PASS=319 WARN=19 ERROR=0 TOTAL=338`. The 19 warnings are baseline tests above
  zero and within their ceilings. A wrapper copy edited after the last load fails the build until
  `load_readings.ps1` is run again.
- `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q`: 141.
- `.\warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>`: the CI
  fixture build (`ci/README.md`). Last result: build `PASS=176 WARN=0 ERROR=0 TOTAL=176`, unit-test and
  wrapper drift step `PASS=15 TOTAL=15`.

### Counts (all parsed filings of the five funds, 288,935 contexts)

| Role | Contexts | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|---:|
| not_schedule | 127,434 | 29,399 | 35,850 | 21,152 | 22,652 | 18,381 |
| comparative | 84,732 | 27,200 | 27,702 | 11,583 | 8,688 | 9,559 |
| position | 74,495 (63,725 published) | 21,191 | 24,734 | 11,943 | 8,034 | 8,593 |
| aggregate | 1,766 | 404 | 47 | 62 | 1,253 | 0 |
| unresolved | 470 (ceiling 470) | 190 | 2 | 116 | 162 | 0 |
| superseded | 38 | 12 | 4 | 0 | 16 | 6 |

Comparison, published basis, compared quarters (key: accession and context):

| Fund | Both | New only | Production only |
|---|---:|---:|---:|
| Ares | 19,767 | 2 | 12 |
| BCRED | 15,499 | 32 | 0 |
| Blue Owl | 9,719 | 1 | 0 |
| Apollo | 7,248 | 0 | 50 |
| HPS | 8,442 | 0 | 0 |
| Total | 60,675 | 35 | 62 |

Unpublished basis (JV schedules): both 10,740, new only 30 (BCRED cash), production only 0.

Causes of one-sided rows, published / unpublished: needs_correction 52 / 0 (values printed, not tagged;
corrections are not applied yet); needs_store_not_loaded 12 / 0 (Ares rows production adds from an
agent store, 8; an Ares rate-only context pair, 4); convention 31 / 30 (cash kept here, dropped by
production, D13); not_yet_explained 2 / 0 (BCRED Box Co-Invest c-1259; Blue Owl LSI Financing c-1013);
new_wrong, owner_review, old_wrong 0. Each has its own ceiling.

Left out of the comparison (production has no rows, D13): Ares, Blue Owl and Apollo at 2026-09-30
(pinned in `cmp_excluded_quarters_pinned`). Filing selection: 74 of 79 fund-quarters select the same
accession as production; differs 0. The other 5: the three 2026-09-30 filings above, which production
has no rows for, and two quarters refused with `no_candidate_with_position_facts` (BCRED 2022-06-30,
HPS 2022-12-31), where production has no rows either (`scripts/slice2/q_ff_f9_selection.sql`).

Final fix wave: no role, cash flag or comparison row moved (F2, F5, F7). The cash convention's detail
now names its source: `cash_published_d7_seed_pattern` 31 / 28, `cash_published_d7_fund_rule` 0 / 2.
Wrapper drift is checked at build time in SQL for both the production wrappers and the copies (F1).

### Owner decisions still open

1. Whether unfunded-commitment lines (Blue Owl; HPS JV) and zero-value lines (34 Ares undrawn revolvers,
   7 equity lines) belong in the position set at all (D11, D15; after reproduction).
2. What the fair value on HPS's JV commitment lines is (about 1 pct of the commitment; not established).
3. Apollo rollups the subtotal rule removes whose cost differs from the rows beneath by more than 10 pct
   (Chemicals Heubach, Media Material+): an untagged position may sit beneath.
4. The two not_yet_explained rows (c-1259, c-1013): why production omits them was not established.
5. Whether the findings ledger moves onto dbt (from step 1; no decision).
6. DONE 2026-11-22: branch pushed to `origin/ensemble-fp-experiment` at ab299286 (owner's go). Items 1
   to 4 stay deferred until after reproduction; item 5 deferred (owner agreed 2026-11-22).

### Controller rulings: CONFIRMED by the owner 2026-11-22

All rulings below were confirmed by the owner in session on 2026-11-22 ("push and confirm rulings").
From the slice 2 ledger and the baseline document.

- The global rule 7 branch: a member on the us-gaap subsidiary or equity-method investee axis sets the
  scope (moves 1,416 Blue Owl rows to the JV basis; both sides agree on them).
- Cause `owner_review` added to the closed list (now 0 rows).
- Rule fixes after the comparison: InvestmentOwnedBalancePercentOfShares as a term fact; rule 8 allows
  the affiliation axis beside the cash axis; wider money-market patterns.
- Ares ownership percent in its own namespace read as a term fact, and Apollo's fair value after cash
  equivalents read as fair value (fund rules in the wrapper copies).
- Ceilings may be set to measured counts where every added row is explained.
- Blue Owl c-1013 stays not_yet_explained (ceiling 2) with detail relabel_loaded; its relabel is in the
  copy only, not in production's wrapper, so production still lacks it.
- The Apollo subtotal rule keeps all 140 rollups, including the 20 whose cost cannot be compared.
- A changed production wrapper fails the build (ceiling 0), rather than warning.
- The Blue Owl Insight CP blocker rule is bounded to 2023-03-31 and is a correction to make in slice 5.
- Task 4: the CI job runs the parser and loader on a committed text fixture rather than committing their
  Parquet output; the comparison models and every baseline test except the wrapper-drift one are left
  out of the CI build (`ci/README.md`).

### Deferred (minor, from the ledger)

- Filing selection: the spec does not name the rule "schedule dated after the period end"; of the
  refusal reasons, only two_originals_same_quarter is exercised by a fixture (the CI fixture).
- Row roles: aggregates inside a JV schedule get scope `fund`; a nil-only fair value context is
  unresolved rather than not_schedule (0 cases); a real company whose label starts with "Total" is
  unresolved; the money-market pattern misses two words between "money market" and "fund" (plurals
  and the hyphen were added in the final fix wave); 39
  Blue Owl "Total ... Commitments" lines are unresolved rather than aggregate (not published either way).
- Unit-test gaps: int_source_row lacks cases for rule 6 with a term fact, rule 5 aggregates and rules 1 to
  3; rules 5 and 6 aggregates and a cash row with a matching fund rule; the two-rule test bites only on
  BCRED and Ares pairs. Cause rules: the catch-all unit test and, since the final fix wave,
  `cmp_row_set_early_causes`.
- Rule table: the loader accepts regular expressions RE2 refuses (atomic groups, possessive
  quantifiers); the overlap test compares namespace patterns by string equality and covers three
  actions; the cost-gap query hard-codes 10 pct.
- Comparison: wrapper dispatch sections were not read.

### Next: slice 3, amounts

Fair value, cost, principal (and its unit), shares, and share of net assets, for every position row:
read from the tagged facts (`int_field_read`), converted by the actions in `seeds/reading_action.csv`
marked slice 3 (`as_filed`, `to_usd`, `reported_in_usd`, `par_tagged_as_units`, `units_tagged_as_par`,
`bracketed_unsigned`, `cost_foreign_is_par`; `int_field_normalised`), and compared with production to
the dollar for fair value, cost and principal (D1), every difference listed with a cause. Corrections
are applied in slice 5, rates in slice 4.

A separate draft spec, `docs/text_fields_spec.md`, covers reading printed and label text into fields.
It is not part of this slice or of slice 3; it starts after the spine reproduces production. (The file
is untracked in this checkout.)

## State after slice 3 (amounts), 2026-11-22 (supersedes "Next: slice 3" above)

A passing build and agreement with production show the layer is consistent and agrees with the old
pipeline where stated. They do not show the data is correct: a value both pipelines read wrongly in
the same way counts as equal, and no test sees a field whose meaning changed.

### What is built

| Piece | What | Commits |
|---|---|---|
| Plan | `docs/2026-11-22-slice3-amounts-plan.md` | 81a17da6 |
| Task 1 | seed `concept_map` (every standard concept named once; no SQL names one), `cash_source`, row-store drift check, two slice 2 parked items | 43ab947e, fbb6cf65 |
| Task 2 | `int_field_read`: the five amount fields as filed, with unit, fact id and printed text | 8ba34a8b |
| Task 3 | `stg_fx_rate`, `int_field_rule` (which rule converts each field), `int_field_normalised` (the value after the rule); seeds `field_rule_default`, `action_field`; `reading_action` gained `built_early_for_field` | 12c5eb55, 7caf2b9b |
| Task 4 | `cmp_amount`: amounts against production, every difference with a cause; action `concept_is_cost`; split-bracket sign fix | 3c6e361c, 622833e3, 2e64f76e |
| Task 5 | CI fixture amounts and `tests/ci_fixture_expected_amounts.sql`; these records | a4189da1 |
| Final fix wave | F1 to F8 of the whole-branch review (below) | see "Final fix wave" |

Plain-language guide: `README.md`, "Amounts: reading and converting a field". Counts and causes:
`docs/baseline_amounts_2026-11-22.md`. Value-size rules for review:
`docs/owner_review_value_size_rules_2026-11-22.md`. Ledger and task reports:
`.superpowers/sdd/2026-11-22-slice3-amounts-plan/` (git-ignored).

Fund rules added to the wrapper copies in this slice (each with its evidence in the rule): Blue Owl
`reported_in_usd` for one cost (filing 0001812554-26-000047); Blue Owl `as_filed` share of net assets
for filing 0001812554-23-000022 (the filer tags the percent itself); Apollo two `concept_is_cost` rules
(its own cost concepts, 196 rows). Production's wrappers are unchanged.

### Not pushed

The slice 3 commits (81a17da6 to a4189da1, and the final fix wave after it) are local only. They have NOT run on GitHub. The
last push (ab299286, run 45015590307) ran slice 2: `warehouse` job passed; `frontend-build` and
`python-tests` failed for the reasons outside `warehouse/` given above (checked again 2026-11-22 with
`gh run view`, no change).

### How to run, and the last results

From the repository root, in PowerShell.

| Command | Last result |
|---|---|
| `.\warehouse\dbt.ps1 build` | `PASS=534 WARN=46 ERROR=0 TOTAL=580` after the final fix wave (Task 5: 503 / 43 / 546; slice 2 ended at 319 / 19 / 338) |
| `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q` | 144 passed |
| `.\warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>` | build `PASS=281 WARN=0 ERROR=0 TOTAL=281`; empty run of the two comparison models `PASS=2`; unit-test and drift step `PASS=24` |

The warnings are baseline tests above zero and within their ceilings. A changed seed column needs
`.\warehouse\dbt.ps1 seed --full-refresh --select <seed>` once in an existing database (a new database
needs nothing).

### Counts

Comparison with production, published basis, rows on both sides (60,675), compared quarters (the
three 2026-09-30 quarters are left out):

| Field | Equal | Differs | Empty here | Empty in production | Both empty | Not yet explained |
|---|---:|---:|---:|---:|---:|---:|
| fair_value | 60,673 | 2 | 0 | 0 | 0 | 0 |
| cost | 58,646 | 13 | 1 | 0 | 2,015 | 0 |
| principal_amount | 49,554 | 0 | 5 | 180 | 10,936 | 14 |
| principal_amount_currency | 48,803 | 201 | 81 | 730 | 10,860 | 0 |
| principal_amount_usd | 49,362 | 191 | 5 | 180 | 10,937 | 14 |
| shares | 7,496 | 157 | 91 | 19 | 52,912 | 0 |
| pct_of_net_assets | 20,112 | 0 | 0 | 0 | 40,563 | 0 |

JV schedules (10,740 rows): fair value and cost equal on every row with a value.

| Cause group | Rows | What it means |
|---|---:|---|
| needs_correction | 716 field rows (718 before the final fix wave) | a loaded correction sets the field and either production names the field or the correction carries production's value; corrections are applied in slice 5 |
| owner_review, unverified unit count read as principal | 107 principal, 107 dollar principal | production empties principal on equity and fund classes; this layer stores the tag, a unit count in the samples read, as a dollar principal (was "convention" until the final fix wave) |
| convention, count currency | 671 currency | principal taken from a share count: production leaves the currency blank, this layer writes USD. That the count is a dollar par is unverified |
| owner_review, "is a loan" stand-in | 59 per principal field, 34 shares (plus 15 JV each) | see open items |
| owner_review, "is equity" stand-in | 14 shares | same |
| old_wrong | 2 share of net assets, 2 principal, 2 dollar principal (all BCRED JV schedule) | production keeps 0.526 where 52.60 is printed; production empties a par a correction reclassed to loan |
| not_yet_explained | 14 principal, 16 dollar principal | 14 each: BCRED STRUCTURED_CREDIT units whose principal production empties, step not found. 2 dollar principal: an Apollo EUR / GBP principal correction production converted; this layer does not convert a correction, so the match is not shown |
| new_wrong | 0 | 85 sign and 196 cost rows found in Task 4, fixed, now equal |

Fields left empty in this layer, each with a ceiling: share of net assets none (was 30,759 before
`fraction_to_percent` was built early); principal `values_differ` 1 (Apollo, GBP and EUR); its dollar
principal 1; dollar principal `no_fx_rate` 130 (129 at 2026-09-30, the rate file ends 2026-09-11; 1
Apollo principal tagged KPW). `int_field_read` unresolved: cost 3, principal 1.

Sum check (positions against the filed total, step 1 basis): 25 fund-quarters do not tie, every one
explained by a named group within 6,000 dollars: BCRED 14 (cash rows, D13), Ares 3 and Apollo 5 (rows
production adds from corrections and stores), 3 with no filed total (2026-09-30). A tie of sums is a
proxy: it cannot see which row carries which value, or offsetting errors.

`int_source_row` (288,935 rows) and `cmp_row_set` (71,542) did not change in this slice (checked by
row snapshots in Tasks 1 and 4).

### Final fix wave (2026-11-22, after a4189da1)

The whole-branch review's findings F1 to F8, fixed in one dispatch. Report:
`.superpowers/sdd/2026-11-22-slice3-amounts-plan/final-fix-report.md` (git-ignored).

| Item | What changed |
|---|---|
| F1 | Every cause on shares and share of net assets has a ceiling, both bases (28 new baseline tests) |
| F2 | `needs_correction` only where production names the field or a covering correction carries production's value; 2 Apollo dollar principals moved to `not_yet_explained`, `correction_loaded_value_not_matched` (a EUR / GBP correction this layer does not convert); unit rows x22, x23 |
| F3 | `tie_break_same_effect` leaves out a loser that cannot be decided; new test fails on a tie-break between rules of different effect (ceiling 0; measured 0 of 462 per field; no value moved) |
| F4 | Cost read in two places pinned: equal on every position row except the 196 read under `concept_is_cost` (ceiling 196). Measured, not built: giving the subtotal rule the filer cost on those rows moves no subtotal decision |
| F5 | The 25 non-tying fund-quarters pinned by key (`sum_not_tied_pinned`); the sum check is now macro `sum_not_tied_rows` |
| F6 | `action_field` key test; every fund rule of a slice 3 amount action must reach an `action_field` row, with target `amount` or one of its fields (all pass; no wrapper changed) |
| F7 | The 107 equity-class principals are `owner_review`, `unverified_unit_count_read_as_principal`, not a convention; unverified items listed above |
| F8 | concept_map note; "normalised without a value" test; this file; CI README context counts |

Guard: `int_source_row`, `cmp_row_set`, `int_field_read`, `int_field_normalised` and `int_field_rule`
(all columns but `tie_break_same_effect`, which also did not move) are row-for-row unchanged;
`cmp_amount` changed only in cause and detail on 216 rows (107 + 107 + 2)
(`scripts/slice3/out/fw_guard_after.txt`). A passing build and agreement with production do not show
the data is correct.

### Owner decisions open

1. Unfunded-commitment and zero-value lines in the position set (D11, D15): still deferred until after
   reproduction.
2. HPS JV commitment lines: the fair value is that of the undrawn delayed-draw tranche, printed again
   in the JV schedule. Both pipelines carry it twice on 24 of 35 lines. Headline unaffected (JV rows
   are not published). Keep, drop or flag?
3. The two Apollo rollups (Chemicals Heubach, Media Material+): beneath each sits a position tagged
   except for a zero fair value printed as a dash; its cost equals the gap. This layer drops it,
   production publishes it at 0 from a correction. Which?
4. The 14 not_yet_explained principals (BCRED STRUCTURED_CREDIT units): trace production further, or
   accept as production's error?
5. The tie-break ruling (spec section 5 rule 1, amended): at equal priority a filing-named rule beats a
   feature-named one. Confirm, or make it a conflict (462 HPS rows per field would become unresolved).
6. The "is a loan" stand-in in the value-size rules (a debt term fact instead of production's text
   class), and keep / narrow / retire each `par_tagged_as_units` row mode
   (`docs/owner_review_value_size_rules_2026-11-22.md`).
7. Refreshing the currency rate file (ends 2026-09-11). Needs a download: owner's call.
8. Whether the findings ledger moves onto dbt (open since step 1).
9. Pushing the slice 3 commits.
10. The 107 equity-class principals (Blue Owl, Apollo, HPS; 3,615m fair value): this layer stores the
    principal tag as a dollar principal; in the samples read it holds a unit count. Now `owner_review`
    (final fix wave F7). Keep as principal, move to shares, or leave empty?

### Unverified (not errors found; values nobody has shown to be right)

| What | Rows | Why unverified |
|---|---:|---|
| Equity-class principals read from the principal tag | 107 principal, 107 dollar principal | a unit count in the samples read, stored as dollars (`owner_review`) |
| Principal currency USD on principals taken from a share count | 671 | production leaves it blank and converts as dollars; both agree on the amount; that the count is a dollar par is assumed, not checked |
| Published principals read as filed on rows with no debt term fact | 2,303: Ares 758, BCRED 43, Blue Owl 104, Apollo 20, HPS 1,378 | an upper bound on unit counts stored as principal, not a count of wrong rows; not measured (`scripts/slice3/q_final_checks.sql`) |

### Rulings made without the owner (slice 3), with the cost if wrong

| Ruling | Cost if wrong |
|---|---|
| Work in the main checkout, no worktree, as in slice 2 | A concurrent batch build would see `warehouse/` changes; it does not read them |
| Subagent commits carry "Co-Authored-By: Claude" rather than the session's model line | Trailer wording on a few commits |
| Task 1 (d) may move rows between causes if each is listed; counts by side must not move (0 moved) | A ceiling changes by a few rows |
| `cmp_row_set` rate check reads the seed's field `rate`, which now includes the cash-pay rate concept (0 rows moved) | A future rate-only row with only the cash-pay tag changes cause; visible in the cause ceilings |
| Fund rules for amounts tagged in a foreign unit only where the filing is the evidence or production's wrapper declares it; never from production's values | Some values stay empty until a cause is named |
| The sum check uses the step 1 basis only (fact_fund_period's A04 rule) | None: the stricter reading |
| At equal priority a filing-named rule outranks a feature-named rule; two still equal are a conflict | On the 462 HPS rows the other rule would be right (it gives the same value today) |
| `fraction_to_percent` built early for share of net assets only (production stores a percent: schema doc and code, not values) | A factor of 100 on one field |
| A missing row feature is an error (`feature_missing`, ceiling 0), not "no match" | One extra test |
| Blue Owl filing-scoped `as_filed` for share of net assets (filing prints 4.0 and tags 4.0) | 646 values off by 100 in one filing |
| Fix the split-bracket sign test now (85 rows, one filing) | A sign flipped on a row with an unrelated ")" cell; the unit case and the sum check guard it |
| Add `concept_is_cost` now for the filer that tags cost in its own namespace (196 rows) | 196 costs read from the wrong concept; today they equal production |
| Task 5 amends spec section 5 rule 1 and section 6.4 to match the build, and commits the slice 2 status edits | Owner reverts wording |

Implementer decisions with a cost, also not seen by the owner: production's `cost_reported` is the
compared cost column (identical to `cost` on all 71,477 rows; test ceiling 0); a principal taken from a
share count is given currency USD (671 rows differ from production's blank); the Port Arthur share of
net assets (printed 52.60) and the two BCRED JV principals are `old_wrong`; production's equity-class
list is copied into `cmp_amount`; Apollo's first cost concept rule is dated to 2023-03-31 only; the CI
fixture writes its share of net assets in the unit `pure`, as the five funds do (see Deferred).

### Deferred (minor, from the slice 3 ledger)

- Concept map: `test_no_concept_literals` asserts exactly 11 concepts; one FASB namespace literal stays
  in the `concept_rule_gaps` macro.
- `stg_row_store_drift` JSON path lookup breaks on keys with a quote or backslash (fails safe, unclear
  message); a missing store file is untested.
- `int_context_feature_fair_value_names_rule` uses NOT IN (null-unsafe).
- The `fv` CTE is repeated in five `baseline_filed_fair_value_*` tests; `cmp_row_set` derives the cash
  source itself instead of reading `int_source_row.cash_source`.
- `int_field_read`: one number in two units is unresolved while `int_context_feature` takes it (0 rows);
  `read_rule_id` is the min of two seed ids on a principal spanning two namespaces (0 rows); the
  status-columns test comment promises more than it checks; a diagnostic header mentions negatives it
  does not query.
- `int_field_rule`: the resolution block is duplicated (macro); `listed_rows_without_instrument` ignores
  the whole-filing rule's dates; `par_tagged_as_units` silently beats `cost_foreign_is_par` on one
  context. (`tie_break_same_effect` over-report: fixed in the final fix wave, F3.)
- Seeds: `column_types` config takes effect only on full refresh. (The `action_field` uniqueness test
  and the check that a fund rule's action and target reach a field: added in the final fix wave, F6.)
- `int_field_normalised`: `value_filed` on dollar-principal rows is the normalised principal, not a
  filed value; the 7-day rate boundary is not unit-tested; the model does not check the rate file's
  hash as production does; no test finds another filing that tags share of net assets as a percent.
- Unit units: unit tests and the CI fixture's older facts write `xbrli:pure` / `xbrli:shares`; real
  filings of the five funds write `pure` / `shares`. A filer writing the prefix gets no unit kind and
  no rule (unresolved, visible, counted).
- `cmp_amount`: `filer_concept_not_read` does not compare values; unit row x20 is refused by two
  conditions at once. (Indirect correction cover and the missing shares / share of net assets ceilings:
  fixed in the final fix wave, F2 and F1.)
- Copies of logic noted by the final review (final fix wave: deferred): the split-bracket test is
  written twice (`int_field_rule` `sign_placement` and `cmp_amount` `split_bracket`); "a principal
  taken from a share count is in USD" is written in SQL in two places (`int_field_rule`
  `principal_usd_row` and `int_field_normalised`); the step 1 basis rule (fact_fund_period's A04) is
  copied into the sum check (now macro `sum_not_tied_rows`).
- Process: one implementer sent inline Python once in Task 3 (stopped, no effect); commit 3c6e361c has
  the session attribution footer; two reviewer query files `scripts/slice3/q_review_t4_*.sql` are left
  uncommitted.

### Next: slice 4, rates

`int_field_read` and `int_field_normalised` extended to interest rate, PIK rate, spread and maturity.
Actions to build: `fraction_to_percent` (for rates), `rate_is_all_in`, `rate_is_cash_leg`,
`pik_only_is_coupon`, `pik_only_is_margin`, `printed_margin_cash_plus_pik`. The check "cash leg plus PIK
equals all-in" (spec section 7). Comparison with production as measured differences with causes (D1:
rates are "other fields", not to the dollar). Corrections are slice 5; `int_observation` and findings
are slice 6.

### After the final re-review (2026-11-22, slice 3 closed at aa6fcc48)

The final re-review (Opus) found every fix-wave item addressed and no new blocking issue. A passing
build and agreement with production do not show the data is correct.

Rulings made after the list above, each with its cost if wrong:

| Ruling | Cost if wrong |
|---|---|
| Cost defined in two models is held by a pinned equality test (ceiling 196), not by making the subtotal rule read the filer-concept cost. Measured: it would change 0 subtotal decisions | The subtotal check ignores cost on those rows until a later slice |
| The 107 equity-class principals are `owner_review` (a unit count read as principal, unverified), not `convention` | A label; the owner decides whether this layer should empty them as production does |
| Final-review findings triaged "later" or "drop" stay deferred; one fix wave only | Small defects carried into slice 4 |
| The four residual minors below are parked for the opening of slice 4 | A misleading comment; a test that could miss a null-reason row (0 today) |
| The slice 3 workspace (`.superpowers/sdd/2026-11-22-slice3-amounts-plan/`) is kept | Git-ignored clutter |

Parked for the opening of the slice 4 plan:

- `int_field_rule.sql:19` and `_intermediate.yml:326` name a test file that does not exist; the real
  one is `tests/baseline_int_field_rule_tie_break_different_effect.sql`.
- `scripts/slice3/q_fw_f4_subtotal_with_filer_cost.sql` has two fund names in SQL comments.
- `tests/int_field_normalised_names_rule.sql:22` is null-unsafe: a null value with a null reason passes.
- The 2 dollar principals moved by the correction check share the `not_yet_explained` ceiling (16)
  with the 14 others; they have no ceiling of their own.
- A tie-break whose only losing rule is undecidable is not checked (0 rows today).

## State after slice 4 (rates), 2026-11-23

A passing build and agreement with production show the layer is consistent and agrees with the old
pipeline where stated. They do not show the data is correct: a rate both pipelines read wrongly in the
same way counts as equal, a rate missing on both sides counts as "both empty", and no test sees a field
whose meaning changed.

### Where the work lives

Since 2026-11-23 (owner decision) the warehouse work is on branch `warehouse-dbt`, in the git worktree
`.claude/worktrees/warehouse-dbt`, cut at e44f990c from `ensemble-fp-experiment`. Four folders in the
worktree are junctions (links) to the main checkout: `warehouse\.venv`, `warehouse\data\filed`,
`data\output`, `.superpowers`. They are shared inputs. Remove them with `rmdir` before removing the
worktree, never with a recursive delete.

Operating notes:

1. A fresh Windows checkout writes some wrapper files with CRLF line endings. Until Task 5 the
   wrapper-drift check hashed raw bytes, so this raised a false "production wrapper changed". It now
   hashes the text with CRLF read as LF (`readings_loader` `store.text_sha256`, and the same expression
   in `stg_wrapper_drift`). In an existing checkout run `.\warehouse\load_readings.ps1` once after
   pulling this.
2. A seed that gains a column needs `.\warehouse\dbt.ps1 seed --full-refresh --select <seed>` once in an
   existing database (here: `action_field` gained `unread_input` in Task 3).

### What is built

| Piece | What | Commits |
|---|---|---|
| Plan | `docs/2026-11-23-slice4-rates-plan.md` | 4dcca972 |
| Task 1 | Flag on HPS JV commitment lines whose fair value is printed twice (`int_repeated_commitment_value`, 24 rows); per-detail ceiling for `cmp_amount`; slice 3 parked minors | 4dcca97..b8790dc |
| Task 2 | `int_field_read` reads the rate tag, the cash-pay tag, PIK rate, spread and maturity date (ten fields per position) | e44f990c |
| Task 3 | `int_field_rule` and `int_field_normalised` convert them: all-in rate, cash leg, PIK rate, spread, maturity date, `rate_kind`; legs check; `action_field.unread_input` | cc63ec05, 00b80611 |
| Task 4 | `cmp_rate`: rates against production, every difference with a cause; PIK-only readings switched off (ruling below) | 990713e6, dcf296e1 |
| Task 5 | CI fixture rates and `tests/ci_fixture_expected_rates.sql`; repairs (a) to (i) of the ledger; these records | 1f431224 and the records commit after it |

Plain-language guide: `README.md`, "Rates: reading and converting a rate". Counts and causes:
`docs/baseline_rates_2026-11-23.md`. Questions for the owner: `docs/owner_review_rate_readings_2026-11-23.md`.
Ledger and task reports: `.superpowers/sdd/2026-11-23-slice4-rates-plan/` (git-ignored).

### Not pushed

Nothing of slice 4 is pushed. The step "check the `warehouse` CI job with `gh run view` after the push"
is OPEN: it needs a push, and a push needs the owner's go. The other two CI jobs (`frontend-build`,
`python-tests`) failed on the last push for older reasons outside `warehouse/`.

### How to run, and the last results

From the repository root of the worktree, in PowerShell.

| Command | Last result |
|---|---|
| `.\warehouse\dbt.ps1 build` | `PASS=660 WARN=112 ERROR=0 TOTAL=772` (Task 4 ended at 648 / 91 / 0 / 739; slice 3 at 534 / 46 / 0 / 580) |
| `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q` | 146 passed (144 before Task 5) |
| `.\warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>` | step 4 `PASS=3`; build `PASS=313 WARN=5 ERROR=0 TOTAL=318`; empty run `PASS=2`; unit-test and drift step `PASS=33` |

The warnings are baseline tests above zero and within their ceilings.

### Counts (published basis, 60,675 rows on both sides, compared quarters)

| Field | Equal | Differs | Empty here | Empty in production | Both empty |
|---|---:|---:|---:|---:|---:|
| interest_rate (all-in) | 33,155 | 8 | 1,304 | 9 | 26,199 |
| interest_rate_cash | 2,450 | 72 | 234 | 6 | 57,913 |
| pik_rate | 5,215 | 90 | 126 | 13 | 55,231 |
| spread | 45,614 | 5 | 962 | 426 | 13,668 |
| maturity_date | 7,023 | 0 | 44,006 | 0 | 9,646 |
| rate_kind | 59,360 | 1,315 | 0 | 0 | 0 |

`not_yet_explained` 0 and `new_wrong` 0 on every field and both bases. Every open row has a cause:
`needs_correction` (corrections, slice 5), `needs_store_not_loaded` (an input not read yet: printed
text, identifier text, or one of two wrapper procedures), `owner_review` (production decides by the
size of the number). Maturity: only Apollo tags it; every other fund's maturity in production comes
from the printed row.

Left empty here by design, each under a ceiling (all rows, all quarters):

| What | Rows | Why |
|---|---:|---|
| Rows with only a PIK tag: all-in rate, cash leg and spread | 1,885 (Ares 1,195, Apollo 62, Blue Owl 460, HPS 168) | `text_not_read`: both PIK-only readings need the printed rate type and the loan class. The PIK rate itself is read |
| Spread on rows with a spread and a PIK rate (Blue Owl 321, Apollo 219) | 540 | `text_not_read`: needs the printed total margin |
| Values filed above 1 in a ratio unit | 767 (rate 679, PIK 20, spread 68) | `scale_not_decided`: not rescaled by size |
| Cash leg where no PIK rate is read | most rate rows | production leaves it empty too (ruling below) |

Two wrapper procedures are measured, not built: Ares `rate_only_contexts adopt_adjacent` (7 pairs),
HPS `pik_margin_reading whole_coupon` (about 171 candidate rows; production changed 49).

`int_source_row`, `cmp_row_set`, `cmp_amount` and every amount row did not change in this slice
(row snapshots in every task).

### Owner decisions open (slice 4)

From `docs/owner_review_rate_readings_2026-11-23.md` section 6 and the plan:

1. PIK-only rows carry no rate until printed text is read (1,885 rows). Wait for the text spec, or a
   dated filer-level rule with evidence.
2. Cash leg where no PIK rate is read: empty (as production's code) or equal to the all-in rate. 40,410 cash-leg rows of 74,495
   are empty for this reason (`no_pik_read`; 28,768 more have no fact). The PIK-only cash contract is carried by unmerged work:
   branches `asif-identity-20261113` and `codex-wip-20261114` on GitHub (the 2026-11-13 changelog line "cash = 0 for
   PIK-only coupons" refers to it).
3. PIK-only coupons: cash leg empty or 0 (moot while item 1 stands). Same unmerged branches as item 2.
4. Values filed above 1 in a ratio unit (767): production's size rule, a filer rule per filing, or
   leave unresolved.
5. The two wrapper procedures: build each as a general mechanism, or leave the rows as a named
   difference until slice 5.
6. The 540 spread-with-PIK rows: unresolved until the printed margin is read, or another reading.
7. `rate_is_cash_leg` with no PIK rate (0 rows today): unresolved here; production stores the tag as
   the all-in rate when the row text names no PIK.
8. Whether Blue Owl gets a rate reading at all (it tags no interest rate; spec section 10 is the later
   route).
9. Rows where the two rate tags and the PIK tag do not add up: 0 rows on the five funds today.
10. New in Task 5: unit kinds are read from the unit's text, so a filer writing `xbrli:pure` (the
    same unit as `pure`) gets no ratio kind and its rates are `unit_not_pure`. None of the five funds
    writes the prefix (0 rows); the CI fixture pins today's behaviour on one row. Read the unit by
    namespace instead (a model change), or leave it.
11. Pushing slice 4.

### Owner rulings on the list above (2026-11-23, in session)

Recorded, not yet built unless stated. Item numbers are those of the list above.

| Item | Owner ruling | Work it creates |
|---|---|---|
| 1 | Wait for printed text. No fund-level PIK-only rule now | None until the text spec |
| 2 | Cash leg = all-in rate where no PIK rate is read | BUILT 2026-11-23 (branch `warehouse-rate-rulings`): 40,410 cash legs set (reason `cash_equals_all_in`; Ares 11,775, BCRED 22,440, Apollo 305, HPS 5,890). `cmp_rate`: 30,573 published and 8,863 unpublished rows now `production_empty`, cause `convention` `cash_equals_all_in_owner_ruling` (own ceiling); 71 published rows moved from new_empty to differs under their old cause. Residual risk: where the rate cell prints the word PIK and no PIK rate is tagged, the cash leg is not stored (controller ruling R1, fix round 1): 69 rows unresolved `pik_printed_not_tagged` (67 published, 2 unpublished); 40,341 cash legs remain set to the all-in rate. Detail: addendum in `docs/baseline_rates_2026-11-23.md` |
| 3 | PIK-only coupon: cash leg 0 | None while item 1 stands |
| 4 | A rule per filer and filing, with evidence from the printed page. Not production's size rule | BUILT 2026-11-23 (branch `warehouse-rate-rulings`): 17 fund rules `ratio_value_is_percent` in the wrapper copies (Ares 6, BCRED 2, Blue Owl 3, Apollo 2, HPS 4), read by the new model `int_rate_scale`, applied per row only where the row's own print agrees. 759 numbers kept as a percent (rate tag 670, PIK 20, spread 69); every printed number agreed (0 missing, 0 disagree). `scale_not_decided` left: 6 rates and their 6 cash legs (was 679 / 679 / PIK 20 / spread 68). Every former `scale_decided_by_size_in_production` row now equals production. Newly scaled values that differ from production: 1 Ares cash leg (printed "6.00% PIK"; no longer stored since R1) and 3 HPS PIK rates and cash legs (whole-coupon class, existing cause; kept by R2, they contradict the printed coupon; the class holds 44 cash legs and 44 PIK rates). OPEN for the owner: the 6 left are Apollo 0000950170-24-094137 rate tags printed as margins ("S+610"): the tag holds a spread, not a rate, so no rule was written. Detail: second addendum in `docs/baseline_rates_2026-11-23.md` |
| 5 | Leave both procedures as named differences until slice 5 | None now |
| 6 | Wait for the printed margin | None until the text spec |
| 7 | Leave unresolved (0 rows) | None |
| 8 | Blue Owl keeps no rate until the later spec route; a computed rate is not a filed one | None |
| 9 | Leave (0 rows) | None |
| 10 | Read the unit properly in slice 5, with the unit mapping moved to data | Slice 5 |
| 11 | Push slice 4 | Done with this commit |

After items 2 and 4 were built (2026-11-23, branch `warehouse-rate-rulings`, two commits, not pushed):
build `PASS=684 WARN=104 ERROR=0 TOTAL=788`; `warehouse/pytests` 146 passed; CI fixture 3 / 332 / 2 / 34.
Rulings made by the implementer, not by the owner: the scale rule's author is written inside its
evidence text (a separate column would change every rule id); the printed reading (`percent` or
`basis_points`) is part of the rule's parameter; `basis_points` is allowed on a spread only; the
cause for ruling A is `convention` and is checked first in `cmp_rate`; the CI fixture has no scale
rule (the unit test `int_rate_scale_rules_and_print` covers the model).
Fix round 1 (controller rulings R1 to R3, table below): build `PASS=690 WARN=106 ERROR=0 TOTAL=796`; 146 Python
tests; CI fixture 3 / 339 / 2 / 35. Implementer choice in that round: `scale_rule_ids` is documented (it lists
every rate input read for the reading), not narrowed.

### Rulings made without the owner (slice 4), with the cost if wrong

From the ledger (`progress.md`). Each was made by the controller.

| Ruling | Cost if wrong |
|---|---|
| Task 1 (d) may change the cause or detail text of exactly the 2 correction-check principal rows of `cmp_amount` if a separate ceiling needs a separate label | 2 rows relabelled; visible in the snapshot diff; reversible |
| Task 2: the stop condition on the unit was read as covering the prefixed form `xbrli:pure` only (0 rows on the five funds). `utr:Rate` (28k Ares rate facts) was given the pure unit kind in Task 3 as one literal in the `unit_kind` macro (`macros/field_lists.sql`). The ruling asked for this as data; that was not done | Ares rates read on the wrong scale if the literal is wrong; a unit name sits in SQL |
| Task 5 (controller): the unit-kind mapping stays a literal in the `unit_kind` macro for this slice | A unit name sits in SQL until slice 5; no number at risk. Moving it to a seed is proposed for slice 5, where owner decision 10 settles its content |
| Task 3: a rate, PIK rate or spread filed above 1 in a ratio unit, with no filer rule for its scale, is unresolved `scale_not_decided`; never rescaled by size | A true rate above 100 pct is left empty (none expected); a percent tagged at or below 1 passes as a fraction, caught only outside 0 to 40 |
| Task 3: the 628 Blue Owl / HPS PIK-only rows with both readings stay `rule_conflict`, no reading picked (since Task 4 they are `text_not_read`, below) | 628 rows with no rate that production has |
| Task 3: a fund with one PIK-only rule gets it on every PIK-only row. REVERSED in Task 4 (next row) | was: 841 wrong rates; now none |
| Task 3: the cash leg follows production's code: empty where no PIK rate is read | Cash empty where it logically equals all-in; derivable later |
| Task 3: the 540 spread-with-PIK rows get their own reason `text_not_read` (ceiling 540); `feature_missing` stays an error at ceiling 0 | 540 spreads empty that production stores |
| Task 4: both PIK-only readings need printed inputs not read (`unread_input`); every row they would decide is `text_not_read` | 324 published rows (Ares 273, Apollo 51) where the old reading agreed with production now carry no rate; 90 more PIK-only rows in the excluded 2026-09-30 quarter were not compared; 841 wrong values were removed |
| Task 4: `production_corrected_no_loaded_store` stays under `needs_store_not_loaded` (2 published rows) | 2 rows under one cause instead of another |
| R1 (controller, fix round 1 of the rate rulings, 2026-11-23): under ruling A, where the rate tag's own printed cell contains the word PIK on its own (`int_rate_tag_cell`, regexp `(^|[^a-z])pik([^a-z]|$)` on the lowercased cell) and no PIK rate is read, the cash leg is unresolved, `pik_printed_not_tagged`, not set to the all-in rate. 69 rows (Ares 37, BCRED 7, Apollo 3, HPS 22; 67 published, 2 unpublished). `cmp_rate` cause `needs_store_not_loaded` `printed_pik_not_read` (67 published), checked before the correction rule | About 69 cash legs left empty that might equal the all-in rate |
| R2 (controller): the 3 HPS rows c-115 (0001838126-24-000061), c-376 (0001628280-26-020206), c-372 (0001628280-26-033248) keep their scale rules. The scale is right; their PIK tag holds the PIK margin where the page prints the whole coupon as PIK, the whole-coupon class the owner left until slice 5. Their stored PIK rate and cash leg contradict the printed coupon. The class: 44 published cash legs and 44 PIK rates differ from production (3 of them on scale-rule values) | 3 more rows in an already open class |
| R3 (controller): the 6 Apollo rate tags of 0000950170-24-094137 stay without a scale rule. Unlike R2, where the field is right (a PIK rate) and only its meaning within the coupon is open, these tags are in the wrong field: the page prints a margin ("S+610"), so storing them as the all-in rate would be wrong whatever the scale | 6 rates stay empty that production fills (with a margin) |

Implementer decisions in Task 5, also not seen by the owner: the rate expectations are a new test file
beside the amounts one (`tests/ci_fixture_expected_rates.sql`); the fixture keeps one rate in
`xbrli:pure` so the `unit_not_pure` behaviour is pinned; the `needs_store_not_loaded` cause ceilings
are now 0 (every detail has its own); the loader version is 5 (wrapper hashes changed format).

### Deferred (minor, from the slice 4 ledger; not done in Task 5)

- `int_field_normalised` makes two decisions and repeats a case block five times; split into a rate
  model (final review).
- `is_not_numeric` / `not_numeric_count` also mean "no ISO date": rename or comment (final review).
- Six near-identical `scripts/slice4/q_t1_snap_*.sql` files (final review).
- `is_commitment_line` is a heuristic (true on 2,271 Blue Owl rows); its description should say so.
- Field names listed in several places; no test that `read_field` = `field` on the amount rows of
  `concept_map`; no unit-test case for a nil maturity or white space round an ISO date.
- `pik_only_is_margin` unit test has no must-not-touch case; the legs check cannot fail on today's
  code (a regression guard only); `unit_not_pure` is assigned but not reported on spread and PIK rate;
  the `action_is_built` macro counts any slice 4 action as built for any rate field.
- A `cmp_amount_detail_max` / `cmp_rate_detail_max` key without a matching detail test leaves those
  rows uncounted (no guard).
- `cmp_rate_cause_rules` misses two paths; the owner-review file gives ranges, not per-quarter counts,
  for two items; fund names remain in comments of `dbt_project.yml`.

### Left for slice 5 (from the final review of slice 4)

- Split `int_field_normalised` into `int_amount_normalised` and `int_rate_normalised` with a union view, as the first task of slice 5, done only on a 0/0 snapshot diff.
- `int_field_rule` checks an unread input before a conflict at the same rank, so a tie between a text-needing rule and a decidable one would read `text_not_read`; return `rule_conflict` when the top rules are mixed.
- A guard test that every key of `cmp_amount_detail_max` / `cmp_rate_detail_max` has a matching detail test.
- `printed_margin_cash_plus_pik` is marked built in `seeds/reading_action.csv` while the spec says not built.
- No CI fixture row exercises a rate tag with no rate reading declared.
- Fund names remain in SQL comments of `int_filing_candidate.sql`, `int_role_structure.sql`, `marts/fact_fund_period.sql`, `tests/baseline_concept_rule_value_and_term.sql`.
- Move the unit-kind mapping (a literal in the `unit_kind` macro) to a seed.
### Next: slice 5, corrections

Slice 5 applies the loaded corrections (`stg_correction`: the two row stores and the wrapper
correction entries) to the converted values, and compares again. It opens with the owner decisions of
2026-11-23:

1. The list of correction stores that hold entries for the five funds (spec section 11, open point).
2. The two Apollo rollups with a zero-value position beneath: publish the position at 0, as
   production does (production does it by a correction).
3. A one-time trace, with a time limit, of the 14 BCRED structured-credit principals production
   empties; if the step is not found, record them as production's error.

Waiting on it: 716 amount field rows and 520 published rate field rows marked `needs_correction`.

### Plan after this slice (owner, 2026-11-23; a plan, not done)

One catch-up merge of the trunk into `main`, which needs the owner's explicit go. Then short branches
off `main`, one per slice; slice 5 would be the first. (Superseded 2026-11-24 by AGENTS.md: the trunk is
`dev`, `main` is the published site; slice branches come off `dev`. Slice 5 was cut from `dev`.)

## State after slice 5 (corrections), 2026-11-25

A passing build and agreement with production show the layer is consistent and agrees with the old
pipeline where stated. They do not show the data is correct. The corrections applied here are
production's own: applying them makes the two pipelines agree, and no check here compares a correction
with the filing. A value both pipelines hold wrongly in the same way counts as equal.

### Where the work lives

Branch `warehouse-slice5`, worktree `.claude/worktrees/warehouse-dbt`, cut from `dev` at 7eac03c0. Commits 5b200726
(plan) to the Task 6 commit, local, NOT pushed. The plan line "short branches off `main`" (Plan after this slice,
above) is superseded by AGENTS.md: the trunk is `dev`, `main` is the published site; slice branches come off `dev`
and are merged by pull request.

### What is built

| Task | What | Commits |
|---|---|---|
| Plan | `docs/2026-11-24-slice5-corrections-plan.md` (owner answers: all seven decisions as recommended, D20 to D26) | 5b200726, 744d28b8 |
| 1 | `int_field_normalised` split into `int_amount_normalised` and `int_rate_normalised` (a view unites them); macro `rate_reading`; seed `unit_kind`; slice 4 minors | 8dc29093 |
| 2 | Inventory of correction stores; the loader reads the two agent stores (loader version 6); seed `correction_field`; `stg_correction_rule` | df2de147, b8b052b4 |
| 3 | Corrections applied to amounts and to the row set: `int_correction_target`, `int_correction_screen`, `int_correction_fair_value_cell`, `int_row_corrected`, `int_field_reread`, `int_correction_application`, `int_field_corrected` | 253ff75d, d2378a8f, 2b476c24 |
| 4 | Corrections on rates (the rate reading runs again on corrected inputs); `int_rate_adjacent` (Ares rule, D24); `int_rate_corrected_input`, `int_rate_corrected` | 33ae2adb, da17b7e9 |
| 5 | `cmp_row_set`, `cmp_amount`, `cmp_rate` read the corrected values; BCRED trace | 615f863e, 282283ad (review fixes) |
| 6 | Consolidation measurements (baseline section 5), CI fixture corrections, these records | the Task 6 commit |

Plain-language guide: `README.md`, "Corrections: what is applied and what is recorded". Counts and causes:
`docs/baseline_corrections_2026-11-24.md`. Ledger and task reports: `.superpowers/sdd/2026-11-24-slice5-corrections-plan/`
(git-ignored).

### How to run, and the last results

| Command | Last result (2026-11-25) |
|---|---|
| `.\warehouse\dbt.ps1 build` | `PASS=830 WARN=115 ERROR=0 TOTAL=945` (slice 4 ended at 690 / 106 / 0 / 796) |
| `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q` | 175 passed (146 before the slice) |
| `.\warehouse\.venv\Scripts\python.exe warehouse\ci\run_fixture_build.py --work <empty folder>` | step 4 `PASS=3`; build `PASS=428 WARN=5 ERROR=0 TOTAL=433`; empty run `PASS=2`; unit-test and drift step `PASS=45` |

### Counts

Outcomes of the 4,411 loaded corrections (4,414 targets: one identifier text can name several rows):

| Outcome | Targets | Main reasons |
|---|---:|---|
| applied | 1,508 | (amounts, rates, companions; 60 contexts become positions) |
| no_op | 154 | `equal_to_normalised` 126, `evidence_only` 16, `already_absent` 9, `procedure_not_built` 3 |
| rejected | 1 | `bridge_ambiguous` (one Blue Owl identifier names two contexts in production) |
| failed | 8 | `rate_reading_unresolved` 7 (Blue Owl), `conversion_unresolved` 1 (the Apollo cost, owner item c) |
| deferred | 2,743 | `field_not_held` 2,541 (names, classes, industry, reference-rate text, relabels), `no_companion_column` 202 |

Rows corrections make positions: 60 (`correction_supplies_fair_value` 44 Apollo zero lines, `correction_supplies_term`
8, `correction_adds_row` 8 Ares). The production bridge: 67 corrections (D21, a debt).

Comparison with production on the corrected values (Task 5, with the Part A labels of Task 6):

- `needs_correction` was 716 amount rows, 598 rate rows (454 published) and 52 position rows; now 0 everywhere except
  the one Apollo cost (own ceiling 1).
- `not_yet_explained` and `new_wrong`: 0 on every field and basis, except the 2 `cmp_row_set` rows unchanged since
  slice 2.
- No published fair value, cost or principal that was equal before the slice differs now.

Consolidation measures (baseline section 5): all 4,411 corrections are pinned to one row; 8 agent rules are
reusable (all row removals, not applied here). 1,732 of 3,978 value corrections make the same fix to the same
position (production's position id) in two or more quarters; 1,122 of them are on fields this layer does not hold
yet.

### Owner decisions open (slice 5)

| # | Question | State now |
|---|---|---|
| a | Two Apollo spreads (0000950170-24-031479 C_1de7bac0, 0000950170-24-058684 C_a98dfaae): a PIK correction makes the row's spread rule need the printed total margin. Keep the spread as before (4.5, production's value), or leave it unread like its filed peers? | Left unread. `cmp_rate` `owner_review` `pik_correction_leaves_spread_unread`, own ceiling 2 |
| b | The 14 BCRED structured-credit "Units" lines: is the amount a par or a unit count? (next to D17) | Production empties the principal (traced, baseline 4.4); here `owner_review` `principal_emptied_before_section_reclass`, 14 + 14 |
| c | One Apollo cost differs from production (0000950170-24-094137 C_f9b16d68; production 41,554,000). This layer cannot sign the untagged value without its print, so the correction fails (`conversion_unresolved`). An exception to D1 "cost to the dollar": acknowledge it, or fix it (read the print) | Recorded exception, own ceiling 1 |
| d | The production bridge (D21): 67 corrections find their row through production's holdings file. A named debt: they must be re-keyed by context before this layer can replace production | Built, ceiling 67 |
| e | 7 Blue Owl rate corrections no rule can read (`failed`): the rows keep their rate fields as before. Production has no rate on them either | Left failed, both sides empty |
| f | Push branch `warehouse-slice5` and open the pull request into `dev` | Not pushed |

### Owner answers on items a to f (2026-11-25, after the slice)

Detail and evidence: `docs/baseline_corrections_2026-11-24.md` section 6. Branch `warehouse-slice5-owner-items`,
cut from `warehouse-slice5`. This block supersedes the "State now" column of the table above.

| # | Owner answer | State now |
|---|---|---|
| a | Asked how production got 4.5: it is the filed spread tag times 100 (the PIK rate 4.5 is a correction). No change asked | Left unread, ceiling 2, until the printed text is read |
| b | "check" | Checked on all 14: principal equals cost to the dollar, USD, a maturity date. A dollar amount. Now `old_wrong` `principal_emptied_before_section_reclass`, 14 + 14. The header reads "Par Amount/Units" and does not settle it; footnote (1) not read |
| c | Asked why this value and not the others; fix agreed | Fixed: a value a correction supplies is not put to the printed-sign test. The cost applies and equals production. Ceilings now 0. applied 1,509, failed 7 |
| d | "understood" | Unchanged: 67 corrections, a named debt |
| e | Asked for an example (Aptive Environmental, Blue Owl, 12.00% (6.00% PIK)) | Left failed. Candidate for the consolidation exercise: a Blue Owl reading for a fixed coupon tagged as a spread |
| f | "yes" | Pushed; pull request 22 into `dev`. CI: `warehouse`, `python-tests`, `frontend-build` passed; the Vercel preview deployment failed (not examined) |

Results on that branch (2026-11-25): `.warehousedbt.ps1 build` `PASS=833 WARN=113 ERROR=0 TOTAL=946`; `warehouse/pytests` 175 passed. The CI fixture was not run locally (it names nothing changed here); the pull request run covers it. Ceiling raised: published costs changed by a correction 21 to 22 (the Apollo cost, named in `dbt_project.yml`).

Also open, not owner questions yet:

- HPS whole-coupon PIK is not built (D24): a named difference, 44 cash legs and 44 PIK rates.
- The printed rows of the 7 Ares adjacent pairs were not opened (values equal production's on every tagged field).
- The review minors parked in the ledger (Deferred, below).

### Rulings made without the owner (slice 5), with the cost if wrong

From the ledger (`progress.md`, every `Ruling:` line). Each was made by the controller.

| Task | Ruling | Cost if wrong |
|---|---|---|
| Plan | The root `.gitattributes` may be edited only to add a `-text` line for a new hash-bound file; nothing else outside `warehouse/` except the Task 6 changelog entry | One extra line in a root file |
| Plan | Owner answer (b) (apply a zero fair value only where the print shows a dash or zero) binds Task 3 over its "all 44" text | None |
| 1 | `seeds/manager_brand.csv` stays exempt from "no fund name in a seed": it is a generated reference list of all funds, not a rule | One seed carries fund names until it moves to a source |
| 1 | The implementer's foreign-currency pattern (any three capitals except USD) replaces the brief's faulty one | None measured |
| 1 | Seed rows `iso4217:USD/shares` and `utr:Q` (kind other) accepted | None: no value reads them |
| 2 | Four stores outside the plan's table (`agent_anchor`, a `.proposed` section bridge, `fund_highlights_wrappers`, `position_id_registry/retirements.csv`) are not holdings corrections | A value-changing store not applied; Task 5's comparison would show it |
| 2 | Production's B2 "interest_rate 0.0 kind cash" is loaded as `interest_rate_cash`, never as the all-in rate | One Ares row's rate legs |
| 2 | The loader's silent skip of `.review.` files becomes a load error (done in Task 3) | A build stops on a file production would load |
| 3 | The 8 Ares `add_row` contexts may be promoted although their role rule is 1 (owner decision 1 approved loading them; all 8 match production to the dollar) | 8 rows and their ceiling come out |
| 3 | The move of six model bodies into macros stands (tables identical row for row) | A future macro edit affects both runs |
| 3 | Extra models `int_correction_screen`, `int_correction_fair_value_cell`, `int_field_reread`, the FX-rate columns and four new outcome reasons accepted, each under a ceiling | Surface area only |
| 4 | Three `text_not_read` ceilings +1 (Ares c-1268, a taker that takes only a PIK rate) and `cash_equals_all_in` +3 (c-1446, c-1475, c-165), each row named | 4 rows hidden under a ceiling |
| 4 | The printed rows of the 7 adjacent pairs were not opened (the brief asked for 3); values equal production's on every tagged field | A pair both pipelines take wrongly |
| 4 | Review minor 3 (two Apollo spreads lose a value production keeps) is a named difference and owner item (a); reading not changed | 2 spreads empty that production holds |
| 5 | The 14 BCRED principals become `owner_review`, `principal_emptied_before_section_reclass` (done in Task 6 Part A) | A label |
| 5 | Currency detail `filled_principal_currency_blank_in_production` (2) becomes `old_wrong`; `untagged_principal_currency_blank_in_production` (3) stays `convention`, listed as unverified | A label |
| 5 | The Apollo cost that differs from production is a recorded exception to D1, owner item (c) | One cost differs |
| 6 | The wider repeat definitions (the quarter taken from the production row; every repeating fix counted) are the main measure, 1,732; the plan appendix's narrower ones, 1,707, are stated beside them and reconcile exactly | The owner reads 1,732 where 1,707 was meant |

### Deferred (minor, from the slice 5 ledger)

- Task 1: the fund-name guard does not scan `dbt_project.yml` or `pytests/`; 12 copies of the unit_kind input in
  unit tests; a hard-coded target list in `reading_rule_amount_action_has_field.sql`; `rate_rule_wide` takes cik and
  report date from the interest_rate row only; one line over 120 columns.
- Task 2: no automated test that a drift failure fails; floats stored with `repr` in `agent_stores._text`.
- Task 4 review: no unit test of `int_rate_corrected_input`; the branches `pik_above_rate`, `kind_not_decidable`,
  `rate_reading_unresolved` are untested; no unit test of a taker reading its giver's facts;
  `int_field_corrected_rate_legs` cannot fail today; a kind correction equal to the kind before is not an override
  (0 rows); context ids that are UUIDs have no number for the adjacent rule (check before funds 0001766037 and
  0001859919 come into scope); the brief's "6 published rows" was 5.
- Task 5 review: `correction_applied_value_differs` is checked after the mechanism rules and tests only the field's
  own correction id (0 rows affected today); the reviewer's snapshot comparison used the implementer's files.
- Final review: `owner_review|principal_emptied_before_section_reclass` keeps the old signature as its condition
  (nothing checks the section re-class happened; ceiling 14 stops growth, not a swap); `needs_store_not_loaded` is
  also used for production steps not built here (for example the dedupe fill), a pattern older than this slice; the
  README Corrections section says "removing it from the store and reloading" of stores that are production's and
  read-only; the Blue Owl exclusion that selects one identifier is classed reusable by hand; the CI fixture has no
  failed correction; the over- and under-counts of the repeat measure (baseline 5.4).

### Left for slice 6

Owner clarification of D5 (2026-11-25, spec D28): every unresolved row or field is either corrected (it leaves the
list) or deliberately marked as ignored with a reason. The review list is a work queue that goes to zero, not a
report. Slice 6 needs a place to record the "ignored" decision.

- `int_observation`: one row per position, date and field, the published value with its rule and correction
  (spec section 6, the model after the corrections).
- Findings: a correction that did not apply (rejected, failed), an unresolved field and an unresolved row become
  findings (spec section 7, D5).
- The first-run review list for the owner (D5): every unresolved row and field listed once; later runs list only
  new ones.

## RESUME HERE (updated 2026-11-25, after slice 5)

Slice 5 (corrections) is built and committed on branch `warehouse-slice5` (worktree
`.claude/worktrees/warehouse-dbt`), pushed, pull request 22 into `dev`. The owner answered items a to f on 2026-11-25
("Owner answers on items a to f" above; the changes are on branch `warehouse-slice5-owner-items`). Earlier text: next were the owner's answers on
the six open items there (a to f; f is the push and the pull request into `dev`), then slice 6
(`int_observation`, findings, the first-run review list). Branches come off `dev`, not `main` (AGENTS.md).

The text below is the earlier RESUME HERE (after slice 4), kept for its history.

Slice 4 (rates) is built and committed on branch `warehouse-dbt` (worktree
`.claude/worktrees/warehouse-dbt`), NOT pushed. Read "State after slice 4" above. Next: the owner's
answers on the slice 4 decisions, the push and the CI check, then the merge into `main` and slice 5.

The text below is the earlier RESUME HERE (after slice 3), kept for its owner answers.

Slice 3 is closed and pushed (branch `ensemble-fp-experiment`). Nothing is running. Build 2026-11-23:
PASS=534 WARN=46 ERROR=0; 144 Python tests; CI fixture passes locally.

Owner answers, 2026-11-23:

1. Push: done, with `docs/agent_changelog.md` committed whole.
2. The 18 slice 3 rulings: the owner CONFIRMED all 18 (2026-11-23), the tie-break included (a
   filing-named rule beats a feature-named one at equal priority; example shown: HPS 2026-03-31,
   Radwell Parent, LLC 1).
3. The 166 unit-count principals: empty them, as production does (D17 in `intermediate_spine.md`).
   NOT built. No label or term-fact feature separates them (measured); production separates them by
   its text class. They stay `owner_review` in `cmp_amount` until the text spec supplies the class.
4. Currency rate file refreshed from FRED: now ends 2026-11-13 (was 2026-09-11). Additive: no
   earlier rate changed (compared row by row). Principals with no rate fell from 130 to 1 (an Apollo
   principal tagged KPW). This is production's reference package too: its hash changed, so the next
   production build converts the 2026-09-30 principals and its release fingerprint moves.
5. BCRED cash basis (D16): fund rule `filed_total_excludes_cash` in `warehouse/wrappers/0001803498.json`,
   read by macro `filed_total_excludes_cash_declared` (sum check and `fact_fund_period`). Non-tying
   fund-quarters fell from 25 to 11 (Ares 4, Blue Owl 1, Apollo 6; three of them are 2026-09-30 with
   no filed total). The BCRED quarters left the pinned list, so a BCRED quarter that stops tying
   without cash fails the build. Basis: numbers only; the printed schedules were not read, and why
   the filed cash-equivalents figure is empty for BCRED was not examined. A declaration cannot see a
   non-cash row wrongly tagged cash that offsets a missing row.

Owner decisions of 2026-11-23 on the items under "Owner decisions open" above (the owner took the
recommended option on each; none is built yet):

- HPS JV commitment lines carried twice (item 2): flag them, decide keep or drop after reproduction.
  The flag is not built; it joins the parked items that open the slice 4 plan.
- The two Apollo rollups with a zero-value position beneath (item 3): publish the position at 0, as
  production does. Production does it by a correction, so it is built in slice 5.
- The 14 BCRED structured-credit principals production empties (item 4): trace once in slice 5, with
  a time limit; if the step is not found, record them as production's error.
- The value-size rules, `par_tagged_as_units` row modes and the "is a loan" stand-in (item 6): keep
  all as they are until the text spec, then review.
- Items 1 and 8 stay deferred, as below.

Still deferred by the owner until after reproduction: commitment and zero-value lines in the
position set; the findings ledger on dbt.

Next work, once the owner says go: write the slice 4 (rates) plan. It opens with the five parked
minors in the section above. Then slice 5 (corrections; 716 rows wait on it), then slice 6.

Agreement with production is not correctness. Unverified: 671 principal currencies taken as USD;
2,303 published principals on rows with no debt term fact.
