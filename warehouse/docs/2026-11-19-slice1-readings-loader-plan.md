# Slice 1 plan: readings loader and rule table

Date: 2026-11-19. Spec: `intermediate_spine.md`, section 9 slice 1. Owner said "do it" on 2026-11-19.

**Goal.** Put the wrappers' reading declarations and the row-level fixes into two tables dbt can
read. No value in the data is decided or changed by this slice.

**What passing shows.** The declarations and fixes loaded faithfully and repeatably. It does not
show that any of them is right.

## Owner confirmations this plan rests on (2026-11-19)

- Position and borrower ids come from today's holdings (accession and context).
- The 13 step 2 rulings (`filed_layer.md` section 7) are confirmed. Ruling 4 (text cut at 4,000
  characters) was measured first: 3,470 of 1,175,675 facts are cut, all note or text-block facts,
  none on a position; no footnote and no table cell is cut.
- End state: one wrapper per fund holds the rules, plus one list of single-row corrections. The
  other stores under `data/overrides/` are folded in or retired after reproduction, not before.

## Measured before planning

Row fixes for the five funds in the two row-correction files, against today's holdings
(`scratchpad/corr_measure.py`, read-only):

| Measure | Result |
|---|---|
| Entries | 3,911 (2,498 keyed by context, 1,413 keyed by identifier) |
| Match a holdings row today | 3,911. Six identifier-keyed entries match more than one row |
| Field marked as corrected on that row | 3,911 |
| Same row and field fixed twice | 0 |
| On spine fields (amounts, rates, shares, maturity) | about 1,300. The rest are text fields (names, industry, reference rate, class) |

So every entry is live. None can be dropped as stale or duplicate.

## Scope

In:

- Loader for the five wrappers: `source_encodings` and `identifier_format`.
- Loader for `row_corrections.csv` and `row_corrections_by_context.csv`, five funds only.
- Output tables `reading_rule`, `correction`, `not_loaded`, and a manifest, under
  `warehouse/data/readings/` (git-ignored, like the filed layer).
- dbt sources, staging views, a seed listing the closed set of actions, and tests.
- CI job: the warehouse's Python tests and `dbt parse`.

Out, with the slice that takes each:

| Left out | Taken by |
|---|---|
| The other value-changing stores (`agent_investigate_rules`, `agent_b2_corrections`, `agent_anchor`, `bdc_aggregate_row_overrides.json`, `bdc_xbrl_html_section_bridges`, rate grammars and anchors). About 140 lines for the five funds by a crude count | Slice 2 (row roles) and slice 4 (rates), where each one bites |
| Resolving identifier-keyed corrections to a context | Slice 5 |
| Interpreting an action (what `rate_is_all_in` does to a value) | Slices 3 and 4 |
| Checking two rules against the same row for a tie | Slice 2 onward; needs rows |
| A new dated `reading_rules` section in the wrapper (decision D4) | First new rule that needs it. The table already has the date columns |
| CI build on a committed fixture | Slice 2, the first slice with a model to build |

## Tables

`reading_rule`, one row per declaration entry:
`rule_id`, `cik`, `valid_from`, `valid_to`, `validity_basis`, `sel_accession`, `sel_axis`,
`sel_member`, `sel_label`, `sel_feature`, `target`, `action`, `parameter`, `evidence`, `origin`,
`rule_class`, `priority`.

- `rule_class`: `convention`, `vocabulary`, `source`, `scope`, `value_test`, `filing_scoped`.
- `validity_basis`: `stated` where the wrapper gives a date, else `assumed_all_quarters`.
- `priority`: 30 where a filing or row feature is selected, 20 for a filer rule, 10 global.
- `rule_id`: first 16 hex characters of the SHA-256 of the other columns.

`correction`, one row per fix:
`correction_id`, `cik`, `report_date`, `accession`, `context_id`, `identifier`, `field`, `value`,
`value_unit` (added during the build: Apollo prints a currency after some values), `expected_value`, `kind`, `store`, `reason`, `evidence`, `author`, `date_added`.

- `kind`: `value` (sets a field), `relabel` (replaces the position label), `exception` (switches a
  filer rule off for one row), `evidence` (changes nothing).
- `store`: `wrapper:<key>`, `row_corrections`, `row_corrections_by_context`.

`not_loaded`: `cik`, `wrapper_key`, `entry`, `reason`. The declarations that need a procedure.

An unknown wrapper key, or an entry that does not parse, stops the loader. Nothing is skipped
silently.

## Tasks

1. **Wrapper flattening** (`warehouse/readings_loader/wrappers.py`, tests
   `pytests/test_readings_wrappers.py`). `flatten(cik, wrapper) -> (rules, corrections, not_loaded)`.
   Tests: each key class on a small wrapper; dates parsed from `C=CDOR to 2025-03-31`; a filing in
   `par_tagged_as_units` becomes filing-scoped; `not <accession> <context>` becomes an exception;
   unknown key raises; malformed entry raises; same input gives the same ids.
2. **Row-correction stores** (`row_stores.py`, tests `test_readings_row_stores.py`).
   `read_row_corrections(path, store, ciks)`. Tests: cik padded; other funds dropped; empty context
   kept as empty; missing column raises.
3. **Store and command** (`store.py`, `cli.py`, `load_readings.ps1`, tests `test_readings_store.py`).
   Rows sorted by key, written to a temporary folder and moved into place; manifest holds input
   hashes, row counts and content hashes, and no timestamp. Tests: two runs give the same manifest;
   duplicate key raises.
4. **Run on the five funds.** Compare counts with `wrapper_fit_2026-11-19.md` (48 declarations
   loaded, 2 and a half not loaded, 284 row-level entries) and with the measurement above (3,911).
   Any difference is explained in the baseline, not adjusted away.
5. **dbt** (`models/staging/readings/`, `seeds/reading_action.csv`, variable `readings_dir`).
   Tests: ids unique and not null; every action is in the seed; `rule_class`, `validity_basis`,
   `kind` in their lists; `valid_from` not after `valid_to`; the manifest's counts equal the tables.
6. **CI and docs.** A `warehouse` job in `.github/workflows/ci.yml` (Python tests, `dbt parse`).
   `README.md`, `HANDOFF.md`, a dated baseline file, a changelog entry.

Done when: Python tests pass, the loader run twice gives the same manifest, `dbt build` passes, and
the baseline records the counts.

## Result (2026-11-19)

Built. Counts and what was found: `baseline_readings_2026-11-19.md`. 121 rule rows, 3 not loaded,
4,195 corrections; build `PASS=190 WARN=10 ERROR=0`; 97 Python tests. The CI job has not run.
