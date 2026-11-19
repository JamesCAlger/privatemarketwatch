# Readings baseline, 2026-11-19 (slice 1 of the intermediate layer)

What the readings loader produced for the five v0.5 funds, loader version 1. Plan:
`2026-11-19-slice1-readings-loader-plan.md`. Spec: `intermediate_spine.md`.

These counts show the stores were copied faithfully and repeatably. They do not show that any
declaration or fix is right. Nothing is applied to data in this slice.

## Rules: 121 rows

One row per entry of a wrapper declaration.

| Class | Rows | What it is |
|---|---|---|
| vocabulary | 73 | A code or label and its meaning (reference-rate codes 32, industry labels 38, others 3) |
| convention | 21 | How a filer's tag is read (rate, PIK, foreign amounts, cost, margin, currency reference) |
| scope | 9 | JV members and suffixes, cash identifiers, a detached schedule label |
| source | 7 | Which printed column holds the reference rate; Ares's identifier format |
| value_test | 6 | `par_tagged_as_units` row modes. They decide from the size of a number; listed for review |
| filing_scoped | 5 | A reading that applies to named filings only |

- Dates: 5 rules carry a stated date (HPS and Blue Owl reference-rate codes). The other 116 are
  `assumed_all_quarters`. Whether each holds for every quarter is not checked.
- Evidence: no rule carries any.
- Priority: 97 filer rules (20), 24 selecting a filing or row feature (30), no global rule (10).

## Not loaded: 3

| Fund | Declaration | Why |
|---|---|---|
| Ares | `rate_only_contexts: adopt_adjacent` | Needs a procedure |
| HPS | `pik_margin_reading: whole_coupon` | Needs a procedure |
| HPS | `gics_industry_carry_back: through 2025-09-30` | Needs a procedure |

## Corrections: 4,195 rows

| Store | Rows | Kind |
|---|---|---|
| `row_corrections_by_context.csv` | 2,498 | value |
| `row_corrections.csv` | 1,413 | value. Keyed by position label, no context |
| wrapper `relabelled_contexts` (Blue Owl) | 201 | relabel |
| wrapper `untagged_values` (Apollo 57, Ares 6, BCRED 1) | 64 | value |
| wrapper `rate_verification_anchors` (Ares) | 16 | evidence; changes nothing |
| wrapper `pik_margin_reading` "not" entries (HPS) | 3 | exception to a filer rule |

Checks against earlier counts:

- Wrapper row-level entries: 284, as in `wrapper_fit_2026-11-19.md`.
- Row-correction files: 3,911, as measured against today's holdings before the plan. All 3,911
  match a holdings row and the field is marked as corrected on it; no row and field is fixed twice;
  six label-keyed entries match more than one row.
- Rule entries: 121 against "about 130" estimated in `wrapper_fit_2026-11-19.md`. That figure was an
  estimate; this is the count.

## Found while loading

- Apollo has `untagged_values` entries with a currency after the value
  (`principal_amount 40000000 EUR`). The loader stopped on the first one. The correction table gained
  a `value_unit` column.

## Repeatability

The loader run twice gives an identical manifest (input hashes, row counts, content hashes).

## Tests

- Python: 30 new (97 in `warehouse/pytests`), all pass.
- dbt: `PASS=190 WARN=10 ERROR=0 TOTAL=200` (was 166, 10, 0). New: ids unique, every action in the
  closed list (`seeds/reading_action.csv`), class, kind and validity in their lists, dates valid,
  every correction names a context or a label, manifest counts equal the tables.

## Not done in this slice

- No rule or correction is applied. No two rules are tested against the same row.
- Other stores that change published values are not loaded: `agent_investigate_rules`,
  `agent_b2_corrections`, `agent_anchor`, `bdc_aggregate_row_overrides.json`,
  `bdc_xbrl_html_section_bridges`, rate grammars and anchors. About 140 lines mention the five funds,
  by a text search; not opened.
- The 1,413 label-keyed corrections are not yet tied to a context.
- The CI job (`warehouse` in `.github/workflows/ci.yml`) is written but has not run: nothing was
  pushed.

## Update, slice 2 Task 5 (loader version 2)

- Source: the loader now reads the new pipeline's own wrapper copies, `warehouse/wrappers/<cik>.json`
  (owner decision 2026-11-19), not `data/overrides/bdc_xbrl_wrappers/`. Production's wrappers are
  unchanged and are only hashed, for the drift table below.
- Rules: 126 (121 above + 5 class `fund_rule` from the copies' new `reading_rules` lists: Ares 1,
  Blue Owl 2, Apollo 2). Two selector columns added (`sel_concept_namespace`, `sel_concept_local`);
  since the id hashes every column, every rule_id changed.
- Corrections: 4,196. Blue Owl `relabelled_contexts` 202 (was 201): one entry added to the copy for
  0001812554-26-000027 c-1013, whose member names LSI Financing LLC while its facts sit on the
  printed row of OWL-HP FINANCE LLC (`baseline_roles_2026-11-19.md`). Wrapper row-level entries are
  therefore 285 in the copies; production's wrappers still hold 284 (201 relabels).
- New table `wrapper_drift` (5 rows): each production wrapper's SHA-256 when copied
  (`warehouse/wrappers/_source.json`) and now. Changed at load: none.
- The loader run twice gives an identical manifest.
