# Amounts baseline, 2026-11-22 (slice 3 of the intermediate layer)

This layer's amounts compared with production's. Spec: `intermediate_spine.md` sections 7 and 8 (D1).
Model: `cmp_amount`. Production: `stg_holdings`, build of record b1116a. Plan:
`2026-11-22-slice3-amounts-plan.md`, Task 4. State: after Task 4 fix round 1 (the two defects the
first comparison found are fixed; the equity-class convention is narrowed; a unit test covers the
cause rules).

Agreement with production shows the two agree. It does not show either is right. This comparison
cannot see a value both pipelines read wrongly in the same way: such a row counts as `equal`. Nor can
it see a field whose meaning changed, or offsetting errors that leave totals intact.

Build line: `PASS=503 WARN=43 ERROR=0 TOTAL=546` (first comparison: 502 / 43 / 545). Python tests 144. CI fixture
build: build `PASS=277`, empty run of the two comparison models `PASS=2`, unit-test and drift step `PASS=24`.

## How the sides are joined

- Rows: the position rows both sides have (`cmp_row_set`, side `both`), both bases. The three
  2026-09-30 quarters in `cmp_excluded_quarter` stay out.
- Key: accession and context id. One row per accession, context and field.
- Seven fields:

| This layer | Production column | Equal when |
|---|---|---|
| fair_value | fair_value | differ by less than 1 dollar (D1) |
| cost | cost_reported | less than 1 dollar |
| principal_amount | principal_amount | less than 1 (same filed currency on both sides) |
| principal_amount_currency | principal_amount_currency | same text |
| principal_amount_usd | principal_amount_usd | less than 1 dollar |
| shares | shares_held | differ by no more than 0.000001 |
| pct_of_net_assets | pct_of_net_assets | no more than 0.000001 percentage points |

- Tolerances are the var `cmp_amount_tolerance`.
- Shares and share of net assets: both sides read one tag. On agreeing rows the largest difference
  is float rounding of the times-100, below 2e-15 (`scripts/slice3/q_t4_tolerance.sql`). Every real
  difference is 1 or more. So 0.000001 separates rounding from a difference.
- Outcomes: `equal`, `differs`, `new_empty` (production has a value, this layer none),
  `production_empty`, `both_empty`.

### Which production cost column

Production has `cost` and `cost_reported`. `cost` equals `cost_reported`, except where a donor
proxy fills it from an earlier row's fair value (`pipeline/financial_conventions.py`,
`cost_proxies`). The proxy is off (`pipeline/config.py`, `COST_PROXY_ENABLED = False`, owner ruling
2026-10-11). `cost_reported` is the filed cost by construction, so the comparison reads it.

Second measure: on all 71,477 holdings rows of the five funds the two columns are identical
(`scripts/slice3/q_t4_cost_columns.sql`; donor-audit methods `reported` and `not_filed` only).
`cmp_amount` keeps production's `cost` as `value_production_cost`. Test
`baseline_cmp_amount_cost_columns_differ` (ceiling 0) fails if they ever part.

## Headline

Published basis, all compared quarters, rows on both sides. Every row adds to 60,675
(`scripts/slice3/q_t4_headline.sql`).

| Field | Equal | Differs | New empty | Production empty | Both empty | Not yet explained |
|---|---:|---:|---:|---:|---:|---:|
| fair_value | 60,673 | 2 | 0 | 0 | 0 | 0 |
| cost | 58,646 | 13 | 1 | 0 | 2,015 | 0 |
| principal_amount | 49,554 | 0 | 5 | 180 | 10,936 | 14 |
| principal_amount_currency | 48,803 | 201 | 81 | 730 | 10,860 | 0 |
| principal_amount_usd | 49,362 | 191 | 5 | 180 | 10,937 | 14 |
| shares | 7,496 | 157 | 91 | 19 | 52,912 | 0 |
| pct_of_net_assets | 20,112 | 0 | 0 | 0 | 40,563 | 0 |

Before fix round 1: fair value 60,630 equal / 45 differs; cost 58,408 / 55 / 197 new empty.

JV schedules (unpublished, 10,740 rows, every row adds to 10,740): fair value and cost equal on
every row with a value. Differences: principal 17 production empty, share of net assets 2, shares 15
new empty.

Fair value on published rows: this layer's total is 3.272m below production's, all in Apollo
2026-03-31: the two rows whose sign production corrects (needs_correction).

## Per fund and field

Published basis. E = equal, D = differs, NE = new empty, PE = production empty, BE = both empty.

| Fund | Field | E | D | NE | PE | BE | Causes |
|---|---|---:|---:|---:|---:|---:|---|
| Ares | fair_value | 19,767 | 0 | 0 | 0 | 0 | |
| Ares | cost | 19,764 | 0 | 1 | 0 | 2 | needs_correction 1 |
| Ares | principal_amount | 13,965 | 0 | 1 | 0 | 5,801 | needs_correction 1 |
| Ares | principal currency | 13,963 | 0 | 0 | 2 | 5,802 | convention 2 |
| Ares | principal_amount_usd | 13,965 | 0 | 1 | 0 | 5,801 | needs_correction 1 |
| Ares | shares | 5,484 | 0 | 12 | 14 | 14,257 | needs_correction 26 |
| Ares | pct_of_net_assets | 0 | 0 | 0 | 0 | 19,767 | |
| BCRED | fair_value | 15,499 | 0 | 0 | 0 | 0 | |
| BCRED | cost | 15,499 | 0 | 0 | 0 | 0 | |
| BCRED | principal_amount | 14,444 | 0 | 1 | 38 | 1,016 | not_yet_explained 14, owner_review 24, needs_correction 1 |
| BCRED | principal currency | 14,456 | 2 | 1 | 24 | 1,016 | owner_review 24, needs_correction 3 |
| BCRED | principal_amount_usd | 14,442 | 2 | 1 | 38 | 1,016 | not_yet_explained 14, owner_review 24, needs_correction 3 |
| BCRED | shares | 971 | 0 | 24 | 0 | 14,504 | owner_review 24 |
| BCRED | pct_of_net_assets | 15,499 | 0 | 0 | 0 | 0 | |
| Blue Owl | fair_value | 9,719 | 0 | 0 | 0 | 0 | |
| Blue Owl | cost | 7,763 | 0 | 0 | 0 | 1,956 | |
| Blue Owl | principal_amount | 6,926 | 0 | 0 | 102 | 2,691 | convention 86, owner_review 16 |
| Blue Owl | principal currency | 6,960 | 44 | 0 | 24 | 2,691 | needs_correction 44, convention 8, owner_review 16 |
| Blue Owl | principal_amount_usd | 6,887 | 39 | 0 | 102 | 2,691 | needs_correction 39, convention 86, owner_review 16 |
| Blue Owl | shares | 703 | 55 | 29 | 5 | 8,927 | needs_correction 66, owner_review 23 |
| Blue Owl | pct_of_net_assets | 4,613 | 0 | 0 | 0 | 5,106 | |
| Apollo | fair_value | 7,246 | 2 | 0 | 0 | 0 | needs_correction 2 |
| Apollo | cost | 7,178 | 13 | 0 | 0 | 57 | needs_correction 13 |
| Apollo | principal_amount | 6,063 | 0 | 3 | 7 | 1,175 | needs_correction 3, convention 7 |
| Apollo | principal currency | 5,961 | 109 | 80 | 0 | 1,098 | needs_correction 189 |
| Apollo | principal_amount_usd | 5,958 | 104 | 3 | 7 | 1,176 | needs_correction 107, convention 7 |
| Apollo | shares | 197 | 1 | 7 | 0 | 7,043 | needs_correction 8 |
| Apollo | pct_of_net_assets | 0 | 0 | 0 | 0 | 7,248 | |
| HPS | fair_value | 8,442 | 0 | 0 | 0 | 0 | |
| HPS | cost | 8,442 | 0 | 0 | 0 | 0 | |
| HPS | principal_amount | 8,156 | 0 | 0 | 33 | 253 | convention 14, owner_review 19 |
| HPS | principal currency | 7,463 | 46 | 0 | 680 | 253 | needs_correction 46, convention 661, owner_review 19 |
| HPS | principal_amount_usd | 8,110 | 46 | 0 | 33 | 253 | needs_correction 46, convention 14, owner_review 19 |
| HPS | shares | 141 | 101 | 19 | 0 | 8,181 | needs_correction 119, owner_review 1 |
| HPS | pct_of_net_assets | 0 | 0 | 0 | 0 | 8,442 | |

JV schedules: BCRED principal 17 PE (old_wrong 2, owner_review 15), currency 15 PE (owner_review),
dollar principal 17 PE (as principal), shares 15 NE (owner_review), share of net assets 2 D
(old_wrong). Blue Owl and HPS JV rows: no difference.

Full output: `scripts/slice3/q_t4_fund_field.sql`.

## Causes

Each cause is set in `cmp_amount` by a rule on row features, first match wins, never a list of
ids. Each count has its own ceiling per basis and field (`cmp_amount_max` in `dbt_project.yml`).
"FV affected" is production's fair value of the rows in the group, $m.

| Cause and detail | Field: rows (published / JV) | FV affected | Funds | Opened |
|---|---|---:|---|---:|
| needs_correction, correction_loaded(_applied) | fair value 2, cost 14, principal 5, currency 282, dollar principal 196, shares 219 | see below | all five | 6 |
| owner_review, par_tagged_loan_test_stand_in | principal, currency, dollar principal 59 / 15 each; shares 34 / 15 | 1,892.2 / 19.1 | BCRED, Blue Owl, HPS | 3 |
| owner_review, units_tagged_equity_test_stand_in | shares 14 | 586.2 | Blue Owl | 4 |
| convention, production_empties_principal_on_equity_class | principal 107, dollar principal 107 | 3,614.7 | Blue Owl, Apollo, HPS | 3 |
| convention, count_principal_currency_blank_in_production | currency 671 | 22,045.9 | Ares, Blue Owl, HPS | 1 |
| old_wrong, pct_size_bound_keeps_fraction | share of net assets 0 / 2 | 2,165.5 | BCRED | 2 |
| old_wrong, principal_emptied_then_reclassified | principal 0 / 2, dollar principal 0 / 2 | 3.9 | BCRED | 2 |
| not_yet_explained, principal_empty_class_not_equity | principal 14, dollar principal 14 | 65.7 | BCRED | 2 |
| new_wrong | 0 (85 + 196 before fix round 1, now fixed and equal) | | | |
| needs_store_not_loaded | 0 | | | |
| production_stale | 0 | | | |

"Opened" counts the printed rows read in the filed layer (`stg_filed_document_row`, with every
fact on the context) before the cause was named. Queries: `scripts/slice3/q_t4_sample.sql`,
`q_t4_context_facts.sql`.

### Fixed in fix round 1: the two new_wrong groups

**Bracket split across cells (85 rows, Apollo 2023-12-31, filing 0000950170-24-031479).** The filing
prints a negative as two cells, `'(282'` then `')'`. Task 3's bracket test read that as unbracketed, so
43 fair values and 40 costs tagged negative were flipped positive, and 2 costs tagged positive kept
the wrong sign. Production reads raw HTML around the fact (`pipeline/printed_sign.py`) and got all 85
right. Opened 6 rows before the fix (e.g. C_00d5bd4e "11,729 | (282 | ) | (293 | )", C_ec14f008 cost
tagged +30,000 printed "(30 )").

- Fix (controller ruling): `int_field_rule` `sign_placement` now also counts as bracketed a number
  whose own cell opens with "(" and holds no ")" when the very next cell starts with ")". It still
  applies only in filings a `bracketed_unsigned` rule lists.
- Rows whose sign changed (`scripts/slice3/q_t4f1_fields_moved.sql`): 85, all in that filing (43
  fair values and 40 costs back to as filed, 2 costs now flipped). None elsewhere.
- All 85 now equal production. The `bracketed_unsigned` rule now flips 23 costs and no fair value;
  all 23 equal production.
- Sum check, Apollo 2023-12-31: before, published +69.628m against the filed total and +14.628m
  without cash rows; after, +55.000m with cash rows and 0 without. The quarter now ties on the step 1
  basis (its cash rows equal the filed cash equivalents).

**Cost in the filer's own namespace (196 rows, Apollo).** Apollo tags cost as
`InvestmentOwnedAtCostCredit` (190 positions, 2023-03-31) and
`InvestmentOwnedAtCostAfterCashEquivalents` (6 money-market positions, 2025-06-30 to 2026-03-31).
Production reads concept names as substrings in any namespace (`pipeline/bdc_filings.py`
`CONCEPT_MAP`). A search over all five funds (`scripts/slice3/q_t4_substring_concepts.sql`) found no
other filer concept production reads that lacks a fund rule. Opened 3 rows.

- Fix (controller ruling): a new action `concept_is_cost` (`seeds/reading_action.csv`, slice 3),
  read in `int_field_read` exactly as `concept_is_fair_value` is: tier 2, only where the context has
  no standard cost fact. Two fund rules in `warehouse/wrappers/0001837532.json`, namespace
  `http://gwms.apollo.com/*`: the first dated 2023-03-31 only (later filings carry the concept on
  comparative contexts only), the second from 2023-03-31. Evidence in each rule: filing, table
  heading and printed row.
- Tests extended to the new action: `fund_rule_selectors_supported`, `fund_rule_no_overlap`,
  `concept_rule_namespace_gaps` (both rules match filed facts; no namespace missed),
  `int_field_read_rule_resolves`. `int_context_feature` reads only `concept_is_fair_value`, so its
  cost column and every role are unchanged.
- Guard: 196 cost fields moved (190 + 6), none elsewhere. No position carrying the concept also
  carries a standard cost fact (`scripts/slice3/q_t4f1_concept_use.sql`). `int_source_row` and
  `cmp_row_set`: 288,935 and 71,542 rows before and after, 0 moved
  (`scripts/slice3/q_t4f1_roles_moved.sql`).
- All 196 now equal production (one of them is in a foreign unit and is read as dollars by Apollo's
  `reported_in_usd` declaration, as production does).

### needs_correction (718 field rows)

- Rule: a loaded value correction (`stg_correction`, kind `value`) names a field that sets this one,
  keyed by context id, or by accession and production's identifier (label-keyed rows of
  `row_corrections.csv`). Detail `_applied` when production's `corrected_fields` also names it.
- Which correction fields set which compared field is a fixed list in the model
  (`correction_cover`): a principal or its currency also sets the dollar principal.
- Stores (`scripts/slice3/q_t4_correction_rows.sql`):

| Store | Fields it sets here | Funds |
|---|---|---|
| row_corrections_by_context | principal currency, dollar principal, FX rate, cost sign | BCRED, Blue Owl, Apollo, HPS |
| row_corrections (label-keyed) | shares, principal currency, dollar principal, fair value, principal | Ares, Blue Owl, Apollo, HPS |
| wrapper:untagged_values | cost, principal | Ares, BCRED, Apollo |

- Every correction carries its own evidence (printed row, reason). Corrections are applied in slice
  5, so these rows are expected to close then.
- Opened: 3 printed rows (Apollo cost C_22ed3371 printed "(38)" tagged +38,000; HPS c-900 shares
  printed "16,598" tagged 16,598,000; Blue Owl c-1330 principal printed with "EUR" sign, tagged GBP)
  plus the 3 rows whose correction is the Apollo two-currency principal and untagged values.
- The two fair-value rows are the sign-corrected Apollo 2026-03-31 pair already known from slice 2
  (`baseline_filed_fair_value_differs_corrected`).
- Every row production marks as corrected has a loaded correction:
  `needs_store_not_loaded` is 0.

### owner_review: par_tagged_loan_test_stand_in (74 rows; principal, currency, dollar principal, shares)

- Rule: this layer moved a share count to principal (`par_tagged_as_units`), production kept it as
  shares and has no principal.
- Cause: the stand-in Task 3 chose for "is a loan" (a debt term fact: rate, spread, PIK rate,
  maturity) in place of production's text class. Preferred equity that carries a dividend rate passes
  the stand-in; production's text class calls it equity.
- Opened: 3 (BCRED Guidehouse "Preferred Equity | 11.50% | 54,010 | 52,935 | 61,571"; Blue Owl PCF
  Holdco "Preferred equity | 14.00% | 19,423 | 22,779"; HPS Rapid Express Preferred).
- Which side is right is not decided here. It is decision 2 of
  `owner_review_value_size_rules_2026-11-22.md`.

### owner_review: units_tagged_equity_test_stand_in (14 shares rows, Blue Owl 2023-09-30)

- Rule: in the filing a `units_tagged_as_par` rule names, one side took shares from the principal
  tag and the other did not.
- 9 rows: production took shares (its text class says equity), this layer did not (the row carries
  a PIK rate, so the stand-in calls it debt). E.g. c-566 Associations Finance "Preferred Stock |
  13.50% PIK | 35,000,000": production looks right (a share count).
- 5 rows: this layer took shares, production did not (its class is FUND or LOAN, not equity). E.g.
  c-562 CD&R Value Building Partners "LP Interest | 33,061": this layer looks right; production keeps
  neither shares nor principal for it.
- Opened: 4.

### The principal production empties (123 principal rows, same 123 dollar principal)

Signature: production has no principal and no dollar principal but kept the principal's currency;
this layer read the principal tag as filed. `pipeline/unified_holdings.py` (lines 1346-1360) empties
principal and dollar principal on rows whose index class is common or preferred equity or a fund, and
keeps the currency. Fix round 1 (review item 1) splits the signature by production's class:

| Group | Rows | Production class | Cause |
|---|---:|---|---|
| Equity or fund class | 107 | COMMON_EQUITY 60, PREFERRED_EQUITY 26, PRIVATE_CREDIT_FUND 6, PRIVATE_EQUITY_FUND 15 | convention, production_empties_principal_on_equity_class |
| BCRED JV bonds re-classed by a correction | 2 | DIRECT_LENDING | old_wrong, principal_emptied_then_reclassified |
| BCRED warehouse and CLO-equity units | 14 | STRUCTURED_CREDIT | not_yet_explained, principal_empty_class_not_equity |

- **convention (107).** Opened 3 (Blue Owl CD&R "LP Interest | 36,993"; Apollo Ishtar "Common Equity
  - Stock | 38,889 Shares"; HPS Picard "Preferred Shares | 827"). This layer reads the tag and has no
  index class (text fields are the second spec). In at least the Apollo and Blue Owl samples the
  principal tag holds a unit count, not a dollar par: keeping it as principal is not obviously right
  either.
- **old_wrong (2).** Huntington Bancshares (2022-12-31, i4089ebdb...) and GTCR Investors LP A-1 Units
  (2023-09-30, c-4549), both in BCRED's JV schedule. Production's raw extraction carries the
  principal. Its class step empties it; afterwards `_apply_row_corrections` (unified_holdings.py line
  1532, after the class step) re-classes both as LOAN / DIRECT_LENDING from `row_corrections.csv`
  (decision D-021: "Printed in the JV schedule's Bonds section: 'Huntington Bancshares Inc | 4.44 % |
  8/4/2028 | 620 | 598 | 592'"; GTCR "SOFR + 3.00 % | 8.40 % | 9/20/2030 | 3,335 | 3,319 | 3,336").
  The correction does not restore the principal. Both printed rows show a par (620 and 3,335) equal to
  this layer's principal. Opened 2. Rule: the signature, a class that is not equity or fund, and a
  loaded correction that sets the row's index class or asset category.
- **not_yet_explained (14).** Regatta Kilo, HPS Freshwater Warehouse Parent, Pikes Peak Bravo and Balboa
  Bay Loan Funding 2025-3 "Units", 2025-06-30 to 2026-06-30. Production's raw extraction carries the
  principal (e.g. c-1282: 6,298,000, `data/output/bdc_holdings.parquet`). Their final class is
  STRUCTURED_CREDIT, which the step does not empty, and no loaded correction or pinned strategy
  candidate names them (`row_corrections*.csv`, `fund_strategy_correction_candidates.pinned.csv`
  searched). Their text has none of the structured-credit keywords (`classification.py`
  `_STRUCTURED_CREDIT_KEYWORDS`). Read but not traced to a conclusion: the classification passes after
  the class step (stabilisation, deterministic restore, strategy corrections, the class caches). The
  likely shape (emptied under an equity or fund class, re-classed later) is a hypothesis, not
  evidence. Opened 2 (c-1282 "Units | 6,298 | 6,298 | 6,948"; c-1232 "Units | 779"). Ceiling 14 each.

### convention: count_principal_currency_blank_in_production (671 currency rows)

- Rule: the principal came from a share count (`par_tagged_as_units`); production's currency is
  blank; this layer writes USD.
- Cause: Task 3 decision 5. Production leaves the currency blank on a principal moved from the share
  tag, and converts it as dollars (`staging_bdc.py`: an empty unit counts as USD). Principal and
  dollar principal agree on all 671.
- HPS 661 (the 2026-03-31 whole-filing rule), Blue Owl 8, Ares 2. Opened: 1 (HPS c-546 Radwell
  "150,328 | 148,172 | 150,328", no currency printed).

### old_wrong: pct_size_bound_keeps_fraction (2 rows, BCRED JV schedule)

- Rule: share of net assets filed above 0.50; production holds the filed fraction unscaled; this
  layer multiplied it by 100.
- BCRED JV schedule, Port Arthur LNG Phase II Class B Units, 2026-03-31 (c-6024, tagged 0.526) and
  2026-06-30 (c-6156, 0.5218). Printed "52.60" and "52.18". Production keeps 0.526 under its rule
  (times 100 only up to 0.50), so it stores 0.526 percent. This layer stores 52.6, as printed.
- Opened: 2.
- Of the four BCRED values above 0.50 expected from Task 3, the other two (0.5987, 0.5943) are on
  rows only this layer has (cash rows in the JV schedule, D13), so they are not compared.
- Blue Owl's 108 values above 0.50 are all in filing 0001812554-23-000022, read by its fund rule
  `as_filed`; they agree with production.

## Task 2 and Task 3 items in this comparison

| Item | Rows | Where it lands here |
|---|---:|---|
| Task 2 unresolved costs (one cost in EUR and USD) | 3 | settled by `cost_foreign_is_par`; all 3 equal production (cost, principal, currency) |
| Task 2/3 unresolved principal (GBP and EUR, two numbers) | 1 | new_empty, needs_correction (production's row correction picks the EUR fact) |
| Its dollar principal (`principal_unresolved`) | 1 | new_empty, needs_correction |
| `no_fx_rate` at 2026-09-30 | 129 | excluded quarters, not compared |
| `no_fx_rate`, Apollo 2024-06-30 KPW principal | 1 | both_empty: production has no dollar principal either (`missing_reference_fx`) |
| Foreign-unit fair value / cost read as dollars (`reported_in_usd`) | 73 / 78 | all equal, except 1 cost with a loaded sign correction (the 78th cost is a filer-concept cost, fix round 1) |
| `par_tagged_as_units` principal | 788 | 714 equal, 74 owner_review |
| HPS 2026-03-31: 665 converted here, 696 in production's wrapper comment | 665 | 660 equal; 5 owner_review (production did not convert). Production converts 660 in this filing, not 696: the comment's figure does not show as a difference. Not followed further. |
| `units_tagged_as_par` shares | 28 | 23 equal, 5 owner_review |
| `bracketed_unsigned` | 23 (104 before fix round 1) | all equal |
| `concept_is_cost` (fix round 1) | 196 | all equal |
| `fraction_to_percent` share of net assets | 30,051 | 30,049 equal, 2 old_wrong |
| Blue Owl PCF Holdco preferred (Task 3 watch item) | | owner_review, par_tagged_loan_test_stand_in |

Unresolved counts of Task 2 and Task 3 are unchanged by fix round 1: `int_field_read` unresolved cost
3, principal 1; `int_field_normalised` unresolved principal values_differ 1, dollar principal
principal_unresolved 1, no_fx_rate 130.

## The sum check

The 25 fund-quarters that do not tie on the step 1 basis (26 before fix round 1;
`baseline_int_field_normalised_sum_not_tied`), against this comparison's groups
(`scripts/slice3/q_t4_sum_explained.sql`, $m):

| Fund | Quarters | Gap | Explained by |
|---|---|---|---|
| Ares | 2022-09-30 | -138.3 | row set: production-only rows, needs_correction 138.3 |
| Ares | 2025-03-31 | -94.3 | row set: production_row_added 94.3 (rate-only pair nets to 0) |
| Ares | 2025-06-30 | -33.2 | row set: production_row_added 33.2 |
| BCRED | 14 quarters | +13.8 to +1,183.4 | row set: new-only cash rows, convention (D13); ex cash the gap is 0 to 0.002 |
| Apollo | 2023-09-30 | -33.3 ex cash | row set: production-only needs_correction 33.3 |
| Apollo | 2024-06-30 | -41.6 ex cash | row set: needs_correction 41.6 |
| Apollo | 2024-09-30 | -12.3 ex cash | row set: needs_correction 12.3 |
| Apollo | 2025-03-31 | -67.2 ex cash | row set: needs_correction 67.2 |
| Apollo | 2026-03-31 | -29.5 ex cash | row set: needs_correction 26.3; amounts: needs_correction -3.3 |
| Ares, Blue Owl, Apollo | 2026-09-30 | | no filed total yet |

Apollo 2023-12-31 left the list in fix round 1 (the bracket fix closed its +14.628m). Every
remaining non-tying quarter is explained by a named group, within 6,000 dollars, and none by this
layer reading an amount wrongly. A tie of sums is a proxy: it cannot see zero rows, which row carries
which value, or offsetting errors.

## Owner items (evidence only, not decided)

### 1. HPS JV commitment lines: what is the fair value beside the commitment?

Read in the printed tables of 2025-03-31 (0001838126-25-000031, table 111) and 2026-03-31
(0001628280-26-033248, table 129); `scripts/slice3/q_t4_owner1_commitment.sql`,
`q_t4_table_rows.sql`, `q_t4_owner1_twins.sql`.

- The lines sit in a separate table under the JV schedule, headed "Investments | Commitment Type |
  Unfunded Commitment | Fair Value". Every line is a "1st Lien Senior Secured Delayed Draw Loan".
- The figure is the fair value of the undrawn delayed-draw tranche. The same company and tranche is
  printed again in the JV schedule above with par equal to the commitment, a negative amortized
  cost, and the same fair value:

| Date | Company | Commitment line | JV schedule row |
|---|---|---|---|
| 2025-03-31 | Brandt Information Services | c-2815: 50,000 / 500 | c-2810: par 50,000, cost (698), FV 500 |
| 2025-03-31 | Compsych Investments | c-2816: 43,333 / 433 | c-2801: par 43,333, cost (206), FV 433 |
| 2025-03-31 | FH BMX Buyer | c-2817: 34,600 / 34 | c-2807: par 34,600, cost (490), FV 34 |
| 2025-03-31 | Rsource Holdings | c-2803: 50,000 / (417) | no row with the same fair value |
| 2026-03-31 | Rsource Holdings | c-3683: 50,000 / (1,462) | c-3669: par 50,000, cost (675), FV (1,462) |
| 2026-03-31 | Sentinel Buyer | c-3684: 19,200 / (125) | c-3654: par 19,200, cost (187), FV (125) |
| 2026-03-31 | Brandt, FH BMX | (292), (308) | no JV row with the same fair value |
| 2026-03-31 | Compsych | 43,333 / dash (0) | not tested (zero) |

- Across all quarters, 24 of the 35 commitment contexts with a non-zero fair value have such a twin in
  the JV schedule (same company, same fair value). Two more match a published row of another company by
  value only, which is coincidence.
- So both pipelines carry the undrawn tranche twice in HPS's JV schedule: once as a schedule row,
  once as a commitment line. Both sides agree, so this comparison does not flag it. The headline is
  not affected (JV schedule rows are not published).

### 2. Apollo rollups with a cost gap above 10 pct (Chemicals Heubach, Media Material+)

`scripts/slice3/q_t4_owner2_rollup.sql`, `q_t4_owner2_side.sql`. Every case has a second position
under the rollup. It is tagged (cost, principal, rate) but has no fair-value fact; its fair value
is printed as a dash. Its cost is exactly the gap.

| Date | Rollup | Rollup cost / FV | Row with FV | Row without FV fact | Gap |
|---|---|---|---|---|---:|
| 2024-12-31 | Chemicals Heubach | 11,002 / 828 | Heubach Holdings USA, cost 1,457, FV 828 | SK Neptune Husky Group Sarl, par 9,588, cost 9,545, FV "-" | 9,545 |
| 2024-12-31 | Media Material+ | 7,951 / 5,642 | Material Holdings term loan, cost 6,375, FV 5,642 | Material Holdings 10.43% PIK term loan, par 1,576, cost 1,576, FV "-" | 1,576 |
| 2025-03-31 | Chemicals Heubach | 9,816 / 243 | Heubach Holdings USA, cost 385, FV 243 | SK Neptune Husky, par 9,588, cost 9,431, FV "-" | 9,431 |
| 2025-03-31 | Media Material+ | 8,109 / 4,051 | Material Holdings, cost 6,533, FV 4,051 | Material Holdings PIK loan, par 1,615, cost 1,576, FV "-" | 1,576 |

- The position is not untagged. Only its fair value is untagged, because it is zero.
- This layer drops those four rows (rule 3: no fair value, `not_schedule`). Production publishes
  them with fair value 0 from its `wrapper:untagged_values` correction. They are among the
  production-only `needs_correction` rows of `cmp_row_set` (see item 3).
- The subtotal rule D12 removes the rollups correctly: they are subtotals. The fair-value tie holds
  because the missing row's fair value is 0.

### 3. The 46 holdings rows whose fair value matches no filed fact (Apollo 44, Ares 2)

`scripts/slice3/q_t4_owner3_nofact.sql`: published production rows whose context carries no
fair-value fact of any concept this layer reads.

| Fund | Rows | Production FV | Dates | Comparison group |
|---|---:|---:|---|---|
| Apollo | 44 | 0 on all | 2023-03-31 to 2026-06-30 | `cmp_row_set` production_only, needs_correction, correction_supplies_value_or_term |
| Ares | 2 | 121.2m | 2025-03-31, 2025-06-30 | `cmp_row_set` production_only, needs_store_not_loaded, rate_only_context_pair (Expereo / Ristretto) |

- Yes: they are exactly two cause groups of the slice 2 row comparison. None is in `cmp_amount`,
  because none is on both sides.
- The Apollo 44 are zero-value lines whose fair value is printed as a dash. The four rows of item 2
  are among them. Production supplies 0 from `wrapper:untagged_values`.
- The Ares 2 sit on the rate-only context of a rate-only / value-only pair. Their value is on the
  sibling context, which this layer publishes (the new-only half of the same pair).

## Tests

| Test | Kind | Measured |
|---|---|---:|
| `cmp_amount_key_and_cause` (one row per key; seven fields per both-sides row; outcome list; cause from the closed list on every open row and only there; numbers and currency in their own columns; is_published equals the basis) | singular | 0 |
| `baseline_cmp_amount_<basis>_<field>_<cause>`: fair value, cost, principal, currency, dollar principal, eight causes each, both bases | baseline, 80 tests | at ceiling (see `cmp_amount_max`); every new_wrong is 0 |
| `baseline_cmp_amount_<basis>_shares_not_yet_explained`, `..._pct_of_net_assets_not_yet_explained` | baseline, 4 tests | 0 |
| `baseline_cmp_amount_cost_columns_differ` | baseline | 0 |
| yml: not_null on keys and outcome; accepted values on basis, outcome, cause | generic | pass |
| unit test `cmp_amount_cause_rules`: invented rows for every cause rule, with a row each rule must not take (split brackets with the same sign; an unrelated filer fact; the equity signature with a non-equity class, with and without a class correction); a quarter in `cmp_excluded_quarter` and a new-only row give no rows | unit | pass |
| unit test `int_field_rule_two_unit_cost_and_sign`, new cases s5 to s8: the split layout flips (s5); NOT: the same layout already negative (s8), a ")" cell after a number with no "(" (s6), a ")" not in the next cell (s7) | unit | pass |

18 of the baselines are above zero and warn; each sits at its ceiling.

CI: the fixture build now runs `dbt run --empty` on `cmp_row_set` and `cmp_excluded_quarter`
before the unit-test step, so the `cmp_amount` unit test can read their column types, as the
`cmp_row_set` unit tests read the stand-in staging views (`ci/run_fixture_build.py`). Result: build 277,
empty run 2, unit-test and drift step 24 (was 23).

## Not checked

- Fields beyond the seven. Rates, spreads, PIK and maturity are slice 4.
- Whether either side is right where they agree. In particular: the 671 currency rows taken as USD;
  the 3,615m of equity principals that are unit counts in the samples read; the Blue Owl zero-value
  commitment lines.
- Rows on one side only: they are slice 2's comparison (`baseline_roles_2026-11-19.md`).
- Which production step empties the principal of the 14 BCRED STRUCTURED_CREDIT units.
- Why production's HPS wrapper comment says 696 rows where production converts 660.
- Funds outside the five; the excluded 2026-09-30 quarters.
