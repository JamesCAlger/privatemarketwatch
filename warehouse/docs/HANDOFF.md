# Handoff: data-model redesign in `warehouse/`

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
