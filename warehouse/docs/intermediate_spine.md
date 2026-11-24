# Intermediate layer, part 1 (the spine): spec

Status: written 2026-11-19. Built so far: slice 1 (readings loader), slice 2 (filing selection,
row roles, comparison of the row set with production) and slice 3 (amounts: field read, conversion,
comparison of amounts with production; 2026-11-22) and slice 4 (rates: the rate tags, PIK rate,
spread and maturity date read, converted and compared with production; 2026-11-23). Not built:
corrections, observations. Counts: `baseline_readings_2026-11-19.md`, `baseline_roles_2026-11-19.md`,
`baseline_amounts_2026-11-22.md`, `baseline_rates_2026-11-23.md`.
Step 3 of the data-model redesign (`design.md`). Follows `filed_layer.md` (step 2).

Passing every test in this spec shows the layer is consistent, repeatable and agrees with the old
pipeline where stated. It does not show the data is correct.

## 1. Purpose

Turn the filed layer (what each filing says) into one row per position per date for the five v0.5
funds, using rules that are data, so that:

- every published value names the rule it was read under and where it came from;
- a change to how a filer is read is a change to a rule row, tested by rebuilding that fund alone;
- what was dropped, and why, is a query.

## 2. Owner decisions this spec rests on (2026-11-19)

| # | Decision |
|---|---|
| D1 | Reproduction test: the row set matches production exactly; fair value, cost and principal match to the dollar; every other field is reported as a measured difference with a cause. |
| D2 | This spec covers the spine only: filing selection, row roles, tagged value fields, conversion, corrections. Fields read from text are a second spec. |
| D3 | Position matching stays in Python. dbt reads its output as a fixed input. |
| D4 | New-style rules are written in the wrapper JSON, in a new section with dates and selectors. A loader flattens them. One place to edit. |
| D5 | A row whose role cannot be decided is left out of the published set and raised as a finding. A field that cannot be decided is left empty and flagged on a published row, and raised as a finding. Each count has a ceiling that fails the build if it grows. On the first run every such row and field is listed for the owner; later runs list only new ones. |
| D6 | Tag against print: the tag wins and the disagreement is recorded. A field the filer never tags is read from print by a filer rule. A normally tagged field missing on one row comes in as an agent correction with evidence. |
| D7 | Cash rows are positions, published, tagged `is_cash`. |
| D8 | Existing wrapper declarations are loaded, not re-derived. Row-level entries in wrappers are loaded as corrections. |

Added 2026-11-19, during slice 2:

| # | Decision |
|---|---|
| D9 | Position and borrower ids come from today's holdings, by accession and context. |
| D10 | All fund-specific rules are stored in one place: the fund's wrapper. No fund-specific logic in the general pipeline. Rules that apply to every fund live in a general table (`seeds/role_pattern.csv`). The new pipeline works from its own copy of each wrapper, `warehouse/wrappers/<cik>.json` (owner 2026-11-19: "copy the wrappers"); production's wrappers and their schema are not changed. A check reports when a production wrapper has changed since the copy. |
| D11 | Blue Owl's unfunded-commitment lines are published as positions, for now, to match production. Whether an unfunded commitment should be a position at all is a question for after reproduction. |
| D12 | An Apollo rollup is a subtotal when its fair value equals the rows below it, even if cost does not. It is an Apollo rule, tested to affect no real row. |
| D13 | Cash is kept and published. BCRED money-market funds that production drops are an intended difference. A fund-quarter production has no rows for is left out of the comparison and counted separately. |
| D14 | The 13 step 2 rulings in `filed_layer.md` section 7 are confirmed. |
| D15 | Real positions that carry no term fact (a fund's own JV or fund interest, equity with no units tagged, a zero-value undrawn revolver, an unfunded commitment line) are released by a fund rule per class in that fund's wrapper. The zero-value classes are included to match production; whether they belong is decided after reproduction, with D11. |

Added 2026-11-23, after slice 3:

| # | Decision |
|---|---|
| D16 | BCRED's wrapper declares that its filed total investments line leaves the schedule's cash rows out (fund rule `filed_total_excludes_cash`, all quarters). The sum check and `fact_fund_period` compare a declaring fund without its cash rows. Basis: the numbers of all 16 quarters; the printed schedules were not read. |
| D17 | A principal that is a unit count (the 166 `owner_review` principals of slice 3: 107 on production's equity and fund classes, 59 moved from a share count by `par_tagged_as_units` where production kept shares) is to be empty, as in production. Not built: the test that separates these rows in production is its text class, which this layer does not read until the text spec. Measured 2026-11-23: no label or term-fact feature separates them (every one of the 166 has a term fact; the narrow equity-word test finds 57 of them and also 24 equal rows and the 14 BCRED structured-credit rows). They stay `owner_review` in `cmp_amount` until the text spec supplies the class; then the rule is general ("no principal on an equity or fund class"), not a list of rows. |
| D18 | Owner ruling A, 2026-11-23 (slice 4 owner item 2): under `rate_is_all_in`, where no PIK rate is read, the cash leg equals the all-in rate (reason `cash_equals_all_in`). Production leaves it empty. Only where the all-in rate itself is normalised. Residual risk: a PIK that exists but is not tagged gives an overstated cash leg. Controller ruling R1 (2026-11-23): not where the rate tag's own printed cell contains the word PIK on its own (regexp `(^|[^a-z])pik([^a-z]|$)` on the lowercased cell, `int_rate_tag_cell`): there the cash leg is unresolved, `pik_printed_not_tagged`. |
| D19 | Owner ruling B, 2026-11-23 (slice 4 owner item 4): a rate, PIK rate or spread filed above 1 in a ratio unit is kept as a percent only under a fund scale rule (action `ratio_value_is_percent` in the fund's wrapper copy) naming the filing, the field and the printed form, with measured evidence and an author. Not production's size rule. Applied per row where the row's own printed number agrees (`int_rate_scale`); other rows stay `scale_not_decided`. Tests: every decided row re-checked against the print, no stale rule, no stored rate built on an undecided number. |

Earlier decisions that still apply: BDCs only, five funds first, per-fund build as the unit, Parquet
and DuckDB, old pipeline keeps running (2026-11-18).

## 3. Scope

In: the five v0.5 funds, every parsed filing, these fields: fair value, cost, principal amount and
its unit, shares, share of net assets, interest rate, PIK rate, spread, and maturity where the filer
tags it. The tag label is carried as filed and not parsed.

Out, for the second spec: borrower name, industry, lien, instrument type, reference rate, footnote
status, maturity where untagged, the heading path of a printed row, any use of a model (Jev) to
propose rules.

Out altogether: the marts switching to this layer (they keep reading the old output until the
reproduction test passes and the text spec is done), moving the findings ledger onto dbt, release
folders, more than five funds, N-PORT, any change to AGENTS.md or the acceptance contract.

## 4. Inputs

| Input | Where | State |
|---|---|---|
| Filed layer | `warehouse/data/filed/` | Built |
| Reading rules and vocabulary | `warehouse/data/readings/` (git-ignored), written by the loader from the wrapper copies `warehouse/wrappers/<cik>.json` (D10) | Built |
| Corrections | same folder, written by the loader from the wrappers' row-level entries and the existing correction stores for the five funds | To build |
| Position and borrower ids | Today's holdings, joined on accession and context id | Exists |
| Currency rates | The reference file the old pipeline uses for `fred_h10`: `data/reference/monetary_conversion/fred_h10_usd_per_unit.csv` (var `fx_rate_file`, read by `stg_fx_rate`). It is the retained source of production's admitted `quotes.json` in the same folder; same currencies, dates and rate text (checked in slice 3). It ends 2026-09-11 (slice 3, 2026-11-22) | Built |
| Production holdings and fund totals | The step 1 staging models | Built |

Ids (D3): in this spec the ids are taken from today's holdings by accession and context. A position
row this layer produces that production does not have gets no id and is listed. Pointing the Python
matcher at this layer's rows, and the two-part dbt build that needs, is a later change.

## 5. The rule table

One row per rule.

| Column | Content |
|---|---|
| `rule_id` | Stable hash of the rule's content |
| `cik` | The filer; empty for a global rule |
| `valid_from`, `valid_to` | Report dates; empty means open |
| `validity_basis` | `stated` or `assumed_all_quarters` |
| selector columns | Row features: concept, unit, axis, member pattern, accession. All that are filled must match. Never a row or context id |
| `target` | A field name, or `role` |
| `action`, `parameter` | From the closed list in section 7 |
| `evidence` | Filing and printed row, where known |
| `origin` | `global_default`, `wrapper:<key>`, `agent_proposed`, `owner` |
| `priority` | Row-feature rule above filer rule above global default |

Rules of use:

1. The most specific matching rule wins. Two equally specific matches are an error, not a tie-break.
   As built (slice 3, 2026-11-22): higher priority wins first. At equal priority, a rule that names
   a filing outranks a rule that names only a row feature (a filing is the narrower scope;
   production's `par_scale` gives the listed filing precedence). Two rules still equal after that
   are an error: no rule is chosen and the field is unresolved (`rule_conflict`). Controller ruling
   in slice 3 Task 3, not yet confirmed by the owner; on today's data it decides 462 HPS rows per
   field (principal, shares), and the beaten rule gives the same result on all of them. At the top
   rank (slice 5 Task 1): a missing row feature first (`feature_missing`, rule 2); then two or more
   top rules that mix one needing printed text no model reads yet (`action_field.unread_input`) with
   one that does not are `rule_conflict` (reading the text would not settle which applies); top rules
   that all need such text are `text_not_read`. Before slice 5 a mixed tie read `text_not_read`; 0
   rows of the five funds were mixed.
2. A missing row feature is an error, never "no match".
3. A rule is never edited. It is ended (`valid_to`) and a new one written.
4. Existing wrapper declarations carry no dates. They load as `assumed_all_quarters`.

The loader maps the 45 declarations that fit directly and the 3 filing-scoped ones
(`wrapper_fit_2026-11-19.md`). The 2 that need a procedure are listed as not loaded. The 284
row-level entries go to the corrections table.

## 6. Models

All under `warehouse/models/intermediate/`. One decision each.

| Model | Grain | What it decides |
|---|---|---|
| `int_filing_selected` | fund, report date | Which filing speaks for the quarter |
| `int_source_row` | accession, context | The role of every context, the rule used, the reason |
| `int_field_read` | accession, context, field | The filed value and its source, unchanged |
| `int_field_normalised` | same | The canonical value and the transform applied. A view since slice 5 Task 1: the union of `int_amount_normalised` (amount fields) and `int_rate_normalised` (rate fields; the reading is macro `rate_reading`) |
| `int_field_corrected` | same | The value after corrections; the filed value stays beside it |
| `int_observation` | accession, context | One wide row per position, with ids, `is_published`, `is_cash`, scope |
| `int_reading_finding` | finding | Every unresolved row or field and every failed check |
| `cmp_reproduction` | accession, context, field | This layer against production |

### 6.1 Filing selection

Ported from the pilot (`instance_select.py` on branch `filer-profile-pilot`): count position facts
per candidate filing; the latest filing at least 90 pct as full as the fullest wins; an amendment
with no numeric facts is skipped; anything in between, two originals, or a period-end mismatch is
refused and listed. A period-end mismatch includes a filing whose schedule holds a fair-value fact
dated after the report date (added in slice 2). The 90 pct figure is a placeholder: amendments seen so far were empty or at
least 98 pct full.

### 6.2 Row roles

Roles: `position`, `aggregate`, `comparative`, `superseded`, `not_schedule`, `unresolved`.

Rules in order; the first match decides.

| Order | Test | Role | Uses |
|---|---|---|---|
| 0 | Filing not selected in 6.1 | superseded | structure |
| 1 | No investment identifier member | not_schedule | structure |
| 2 | Date is not the filing's period end | comparative | structure |
| 3 | No fair value | not_schedule | structure |
| 4 | Label reads total, subtotal, net assets, or an affiliation heading | aggregate | text |
| 5 | Label reads cash and cash equivalents, unless it names a money-market fund | aggregate | text |
| 6 | Label is the start of other rows' labels and its fair value (and cost) equals their sum | aggregate | text and sums |
| 7 | Carries a JV entity (member or label suffix from the rule table) | position, scope = the JV | structure or text |
| 8 | Fair value on the cash axis alone | position, `is_cash` | structure |
| 9 | Anything left | position | |

- Rules 0 to 8 are the pilot's published-basis rules (`census_published.py`, version 2), checked there
  on 101 fund-quarters of 8 filers. Of the five funds here only BCRED and Ares were among them.
- Guard on rule 6: a row that reports a rate, spread, PIK rate or maturity, or whose fair value is
  zero, is never removed.
- Cross-check: a position should carry at least one term fact (principal, shares, rate, spread, PIK
  rate, maturity). On Apollo this alone split 8,643 of 8,655 contexts as production does. Where the
  cross-check and rules 4 to 6 disagree, the row is `unresolved`.
- The text patterns of rules 4, 5 and 7 and the axis of rule 8 are data, not SQL. Patterns that
  apply to every fund are rows of the seed `seeds/role_pattern.csv`, which is the general part of
  the rule table and names no fund. Patterns for one fund are `reading_rules` in that fund's wrapper
  copy (D10).
- Rule 6 is built in SQL (`int_role_subtotal`).

### 6.3 Field read

Tagged fields only. For each position and field: the fact, its value as filed, its unit, its fact id,
and the printed text of the same fact. Two facts of one concept on one context with different values
make the field unresolved.

### 6.4 Conversion

| Action | Effect |
|---|---|
| `as_filed` | No change. The global default for amounts in dollars |
| `fraction_to_percent` | Times 100. The global default for a pure-number rate |
| `to_usd` | Foreign principal to dollars at the report date |
| `reported_in_usd` | Amount in a foreign unit taken as dollars, by filer rule |
| `rate_is_all_in` / `rate_is_cash_leg` | Sets which leg the rate tag holds; the other is derived with the PIK rate |
| `pik_only_is_coupon` / `pik_only_is_margin` | Reading of a row that carries only a PIK tag |

Canonical rate fields: all-in rate, cash leg, PIK rate, each stored. Measured on today's holdings at
2026-03-31: the stored `interest_rate` is the all-in rate with the cash leg in its own column, and
the rate is marked unresolved on most rows of Blue Owl (854 of 863) and Apollo (733 of 778).
AGENTS.md was corrected to say so on 2026-11-19 (b2f06350).
Unresolved here includes rows with no rate at all, such as equity; the split was not measured.

Actions as built in slice 3 (slice 3, 2026-11-22). The closed list is `seeds/reading_action.csv`;
which field each fund-rule action acts on, and on which rows, is `seeds/action_field.csv`; the global
defaults are rows of `seeds/field_rule_default.csv`.

| Action | Field | Effect as built |
|---|---|---|
| `as_filed` | fair value, cost, principal, shares; share of net assets by filer rule only | No change. Global default for dollar amounts, shares and a foreign principal (kept in its currency). A filer rule naming it keeps a share of net assets the filer already tags as a percent |
| `to_usd` | dollar principal | Principal times US dollars per unit, at the report date or the latest earlier quote at most 7 days old; none: unresolved `no_fx_rate`. Filer rule (`principal_usd_reference`) |
| `reported_in_usd` | fair value, cost | Amount in a foreign unit taken as dollars. Filer rule |
| `cost_foreign_is_par` | cost, principal | Cost tagged once in dollars and once in another currency: the dollar fact is the cost, the foreign fact the principal. Filer rule |
| `par_tagged_as_units` | principal, shares | A share count on a debt row becomes the principal; shares left empty. Filer rule, row modes decide from the size of the number |
| `units_tagged_as_par` | shares | In a listed filing, an equity row's principal fact is its unit count. Filer rule |
| `bracketed_unsigned` | fair value, cost | In a listed filing, the printed brackets set the sign. Filer rule |
| `fraction_to_percent` | share of net assets only | Times 100. Global default for a pure share of net assets. Built early for this field only (`built_early_for_field`); for rates it is slice 4 |
| `concept_is_cost` | cost | Read side, like `concept_is_fair_value`: the filer's own cost concept is read where the context has no standard cost fact. Filer rule |

Rate actions as built in slice 4 (2026-11-23). The production source of each action is named in the notes of
`seeds/action_field.csv` and by file and function: `pipeline/staging_bdc.py` `_prepare_bdc` (the x100 scaling,
`pik_is_coupon`), `pipeline/financial_conventions.py` `prepare` (the rate reading and the PIK-only readings),
`pipeline/bdc_xbrl_html_bridge.py` `apply_ixbrl_field_status_overlay` (printed margin, reference-rate column),
`pipeline/source_encodings.py` `adopt_rate_only_contexts`, `whole_coupon_pik.py` `apply` / `parse`. An action whose `action_field.unread_input` is set needs printed text no model
reads yet: every row it would decide is unresolved, reason `text_not_read`, under a ceiling.

| Action | Field | Effect as built |
|---|---|---|
| `fraction_to_percent` | PIK rate, spread (global default, ratio unit: unit kind `pure` in `seeds/unit_kind.csv`, which lists `pure`, `xbrli:pure` and `utr:Rate`) | Times 100. A value filed above 1 is not rescaled by its size: unresolved `scale_not_decided` (controller ruling), unless a scale rule keeps it (next row) |
| `ratio_value_is_percent` | the rate tag, cash-pay tag, PIK rate or spread as read (D19) | A number filed above 1 in a ratio unit is already a percent: kept as filed. Filer rule per filing and field; decided per row where the print agrees (`int_rate_scale`). A PIK rate or spread so kept names this rule; the all-in rate and cash leg keep their reading's rule and list it in `scale_rule_ids` |
| `rate_is_all_in` | all-in rate, cash leg, kind | All-in = rate tag times 100, kind `all_in`; cash = all-in less PIK where a PIK rate is read, else cash = all-in (`cash_equals_all_in`, D18; production leaves it empty); PIK above the rate plus 0.01: both unresolved `pik_above_rate`. Filer rule |
| `rate_is_cash_leg` | all-in rate, cash leg, kind | Cash = rate tag times 100, kind `cash`; all-in = cash plus PIK where a PIK rate is read, else unresolved `cash_leg_without_pik`. Filer rule; no fund of the five declares it |
| `pik_only_is_coupon` | all-in rate, spread (row with only a PIK tag) | Built (all-in = PIK) but switched off: `unread_input` printed rate type and loan class (controller ruling 2026-11-23, after it gave 841 wrong rates). Rows are `text_not_read`; the PIK rate is still read. Filer rule |
| `pik_only_is_margin` | all-in rate, spread (row with only a PIK tag) | Built (spread = PIK, rate unresolved) but switched off the same way. Filer rule |
| `printed_margin_cash_plus_pik` | spread (row with a spread and a PIK rate) | Not built: `unread_input` printed total margin; rows are `text_not_read`. `seeds/reading_action.csv` labels it `text` since slice 5 Task 1 (it said 4); the label moved no row. Filer rule |
| `as_filed` | maturity date | The filed ISO date. Global default |

A row with both rate tags keeps both where they agree with the PIK rate within 1e-9, else both are
unresolved `legs_do_not_add` (production keeps the first fact in the instance; 0 rows on the five
funds). No rate is derived from a base rate plus a spread (section 10). Two wrapper procedures are
measured, not built: `rate_only_contexts adopt_adjacent` (Ares) and `pik_margin_reading whole_coupon`
(HPS).

The value-size readings in the wrappers (`par_tagged_as_units` row modes) are loaded as they are and
listed for review. They decide from the size of a number.

A transform not on the list fails the build.

### 6.5 Corrections

Each correction names the accession, context and field, the new value, whether it replaces the filed
or the converted value, and the decision or wrapper entry that authorises it. A correction whose
target row does not exist, or whose filed value is not what it expected, is reported and not applied.

## 7. Checks

| Check | Form |
|---|---|
| Keys unique, references resolve, every context has exactly one role | Test, blocks the build |
| Every value on a published row names a rule | Test, blocks the build |
| Cash leg plus PIK equals all-in | Test, blocks the build |
| Positions per fund and date sum to the filed total, on the published basis and the cash basis of step 1 | Test with a ceiling |
| Unresolved rows; unresolved fields | Tests with ceilings (D5) |
| Printed number against tagged number, after the tag's scale | Finding |
| Set of concepts a filer uses changed against the prior quarter | Finding |
| Rate between 0 and 40 after conversion | Finding. A sanity bound only |
| A correction that did not apply | Finding |

Not carried over from the pilot: learned value ranges, identifier-format and yield checks. Measured
there: value range caught 0 of 8 known cases.

## 8. Reproduction test (D1)

`cmp_reproduction` joins this layer to production on accession and context.

| Measure | Requirement |
|---|---|
| Position rows on the published basis | Same set. Every row on one side only is listed with its role and rule |
| Fair value, cost, principal | Equal to the dollar. Every difference listed |
| Other fields in scope | Difference counts per fund and field, each group with a cause: old wrong, new wrong, convention, or not yet explained |

Differences are recorded in a dated baseline file, as steps 1 and 2 did. "Not yet explained" has a
ceiling.

## 9. Order of work

Each slice ends with a build, the comparison, and a baseline entry.

1. Loader and rule table; tier 1 CI (dbt parse, parser tests, a build on one small committed fixture).
2. Filing selection and row roles; compare the row set.
3. Amounts: fair value, cost, principal, shares, share of net assets.
4. Rates.
5. Corrections.
6. `int_observation`, findings, the first-run review list.

## 10. After reproduction: deriving the all-in rate from base rate plus spread

Status: specified, NOT to be built until the reproduction test (section 8) passes. Owner 2026-11-19:
compare like for like first, then improve. It is a deliberate difference from production, so it
cannot be part of the reproduction comparison.

**What it does.** For a floating-rate loan with a filed spread and reference rate but no filed
all-in rate, set all-in rate = base rate at the report date + spread (+ PIK margin where the filer's
printed margin is cash plus PIK).

**Why.** At 2026-03-31 the rate is unresolved on 854 of 863 Blue Owl rows and 733 of 778 Apollo
rows. Both funds file the spread. It would fill 417 of Blue Owl's 448 loans and 599 of Apollo's 615.

**Evidence it works** (measured 2026-11-19, one quarter, SOFR loans with no PIK, on funds that file
both rate and spread): filed all-in rate less spread, against 3.68 in the table.

| Fund | Rows | Median | Within 0.25 of the median |
|---|---|---|---|
| Ares | 754 | 3.70 | 99.2 pct |
| BCRED | 911 | 3.67 | 96.0 pct |
| HPS | 455 | 3.67 | 99.3 pct |

**Form.**

- Input: `data/reference/sofr_90day_avg.csv` (daily, 2018-07-02 onward), loaded as a seed or source.
- A new action, `rate_from_base_plus_spread`, applied only where the rate field is empty after
  section 6.4 and corrections.
- The result carries its own kind, `derived`, and its rule. It is never stored as a filed all-in
  rate and never overwrites one.
- Floor: use the greater of the base rate and the row's floor where a floor is read. Floors are
  printed text, so this waits on the second spec; until then rows are derived without a floor and
  the rule says so.

**Standing check.** On every fund and quarter where both a rate and a spread are filed, the share of
SOFR rows within 0.25 of base plus spread. A test with a ceiling on the miss rate, per quarter.

**Not settled.**

| Point | State |
|---|---|
| Other benchmarks (SONIA, EURIBOR, CORRA and others) | No table in the repo. Rows stay unresolved |
| Tenor and reset date | The 90-day average is a proxy. A few pct of rows sit up to 0.2 above it |
| Other quarters | Only 2026-03-31 measured |
| What production does with this today | It has the same sum (`pipeline/sofr_reference.py`) but uses it to settle conflicting rate readings, not to fill an empty rate. Why it stops there: not checked |
| Effect on income and returns | Not measured. `index_returns` reads the all-in rate, so derived rates would enter income unless excluded by kind. Owner decision before any consumer reads them |

## 11. Open points

| Point | State |
|---|---|
| Subtotal rule in SQL or Python | Closed in slice 2: SQL |
| Identical labels within a filing (19 pairs in holdings) | Ids come from production in this spec, so not hit yet |
| Which existing correction stores hold entries for the five funds | List in the plan |
| The Ares position (Expereo / Ristretto) whose fair value matches no filed fact | Unexplained |
| Step 2 rulings (`filed_layer.md` section 7) | Confirmed by the owner 2026-11-19 (D14) |
