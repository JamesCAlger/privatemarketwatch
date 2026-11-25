# Baseline: corrections (slice 5), 2026-11-24

Section 2 is written by Task 3 (the outcomes of applying the corrections to amounts and to the row set); sections 3
onward by Tasks 5 and 6. Nothing in section 1 applies a correction; it says what the stores hold, what the loader
loads and where production applies each.

Agreement with production, where this file reports it, shows the two pipelines agree. It does not show either is
right: no check here sees a wrong correction or a value both pipelines read the same wrong way.

## 1. Inventory of correction stores (slice 5 Task 2)

Measured from the files and from the loaded tables on 2026-11-24 (branch `warehouse-slice5`, readings loader version
6). Queries: `warehouse/scripts/slice5/q_inventory_*.sql`, run with `warehouse/scripts/slice2/run_sql.py`.
`q_inventory_pre_loader.sql` and `q_inventory_pre_fields.sql` were run before the loader change (8dc29093); the
others after. Funds: Ares 0001287750, BCRED 0001803498, Blue Owl 0001812554, Apollo 0001837532, HPS 0001838126.

### 1.1 Stores with entries for the five funds

Every folder and file under `data/overrides/` was listed and searched for the five CIKs (padded and unpadded).

| Store | Entries (five funds) | Loaded | Can | Where production applies it (verified 2026-11-24) |
|---|---|---|---|---|
| wrapper `untagged_values` | Ares 6, BCRED 1, Apollo 57 | yes (kind `value`) | set a filed value | parse time, `pipeline/bdc_filings.py` lines 1141-1142 `fill_untagged_values` (`pipeline/page_labelled_contexts.py`); conversion runs after it |
| wrapper `relabelled_contexts` | Blue Owl 202 | yes (`relabel`) | replace identifier text | parse time, `page_labelled_contexts.py` |
| wrapper `pik_margin_reading` "not ACC CTX" | HPS 3 | yes (`exception`) | exempt a row from the whole-coupon reading | `pipeline/whole_coupon_pik.py` `apply` (staging) |
| wrapper `rate_verification_anchors` | Ares 16 | yes (`evidence`) | nothing (evidence for a check) | `pipeline/provenance_reverify.py` lines 420-421 (a check) |
| `row_corrections.csv` | 1,413 | yes (`value`) | set or withdraw (empty value) one field; a key matching several rows sets all | `pipeline/unified_holdings.py` `_apply_row_corrections` (call line 1532, assignment line 2452), after classification and printed sections, before the agent stores |
| `row_corrections_by_context.csv` | 2,498 | yes (`value`) | same, one context | same function, read after the first file |
| `agent_b2_corrections` | Ares: `all_pik_normalization` (1 row), `comparative_period_filter` (2025-12-31) | yes since loader 6: the value leaf as 3 `value` corrections; the filter as 1 `stg_correction_rule` row, not applied | set rate fields on one row; remove comparative-period rows | value leaf: `pipeline/agent_promoted.py` `apply_promoted_stage2_corrections` via `apply_promoted_plan` (unified_holdings.py lines 1545-1556); filter: raw staging, `agent_promoted.apply_raw_staging_exclusions` |
| `agent_investigate_rules` | BCRED 2, Blue Owl 4, Ares 6, Apollo 2 live (HPS 0) | yes since loader 6: 2 `row_add` rules as 212 `add_row` corrections (8 positions); 12 `row_exclusion` as `stg_correction_rule` rows, not applied | remove rows; add rows | `agent_promoted.apply_promoted_plan` (unified_holdings.py line 1554); `pipeline/agent_rule.py` `_apply_exclusion`, `_apply_add` |
| after all of them | | | rate legs and kind derived again from the corrected rate, PIK rate and kind | `pipeline/financial_finalization.py` `prepare_artifact`, unified_holdings.py line 1643 |

Checked and not a holdings correction for the five funds (the plan's list, re-checked, plus four it did not name):
`bdc_aggregate_row_overrides.json` (a check, `source_reconciliation.py`); `identifier_spread_corrections.json` (0 for the
five); `bdc_xbrl_oracle_exceptions.json` (check decisions); `rate_convention/`, `identifier_anchors/`,
`identifier_rate_grammars/` (readings); `verdict_retirements/`, `finding_dispositions/`,
`finding_dispositions_proposed/` (decisions). Not in the plan's list:

| Store | Five-fund entries | Why it is not a holdings correction |
|---|---|---|
| `agent_anchor/<cik>/<quarter>.json` | Ares, BCRED, Blue Owl, HPS, Apollo (one quarter each) | Adjudicated grand totals. Read only by `agent_promoted.load_anchor_overrides`, whose callers are `scripts/run_production_acceptance.py`, `scripts/shadow_conservation_engine.py` and audit scripts: a conservation anchor for the gate, not a value in holdings |
| `bdc_xbrl_html_section_bridges/0001838126.proposed.json` | HPS | A proposal: `pipeline/bdc_xbrl_html_bridge.py` `load_html_section_bridge_rows` skips `.proposed` files |
| `fund_highlights_wrappers/0001838126.json` | HPS | Fund-level NAV per share source preference (`pipeline/fund_financials.py`), not holdings |
| `position_id_registry/retirements.csv` | some | Position identity (`pipeline/holdings_finalizer.py` line 139), not a value |

### 1.2 Loaded corrections per store, fund and kind

`q_inventory_store_fund_kind.sql` (after the load). Re-measured against appendix A1 of the plan: every pre-existing
count is equal (4,196). The agent stores add 215 rows.

| Store | Kind | Ares | BCRED | Blue Owl | Apollo | HPS | Total | Key shape |
|---|---|---:|---:|---:|---:|---:|---:|---|
| row_corrections | value | 195 | 18 | 171 | 852 | 177 | 1,413 | accession + identifier, no context, report date on all |
| row_corrections_by_context | value | 186 | 1,132 | 211 | 273 | 696 | 2,498 | accession + context (+ identifier), report date on all |
| wrapper:untagged_values | value | 6 | 1 | 0 | 57 | 0 | 64 | accession + context, no date |
| wrapper:relabelled_contexts | relabel | 0 | 0 | 202 | 0 | 0 | 202 | same |
| wrapper:pik_margin_reading | exception | 0 | 0 | 0 | 0 | 3 | 3 | same |
| wrapper:rate_verification_anchors | evidence | 16 | 0 | 0 | 0 | 0 | 16 | same |
| agent_investigate_rules | add_row | 212 | 0 | 0 | 0 | 0 | 212 | accession + src_context_id, grouped by add_group_id (8 groups) |
| agent_b2_corrections | value | 3 | 0 | 0 | 0 | 0 | 3 | production row_id, report date, no accession |
| Total | | 618 | 1,151 | 584 | 1,182 | 876 | 4,411 | |

Row stores cover 2022-09-30 to 2026-06-30 (per fund 6 to 16 quarters); the agent entries cover Ares 2025-03-31,
2025-06-30 (add_row) and 2025-12-31 (B2).

`stg_correction_rule` (not applied): 13 rows. agent_investigate_rules `row_exclusion` 12 (BCRED 2, Blue Owl 4, Ares 4,
Apollo 2; scope `all` on 6, one dated quarter on 6), agent_b2_corrections `comparative_period_filter` 1 (Ares
2025-12-31).

Files of the five funds in the two agent stores: 24, of which 8 skipped (all `_retired_*`, BCRED 5, Ares 1, HPS 2;
two of them are also `.review.` records). No `_pulled` file of the five sits at the depth production reads
(`<store>/*/*.json`); `agent_b2_corrections/0001287750/_pulled_noop_setcash_20260821/` is one level deeper and is read
by neither.

### 1.3 Per fund and quarter

`q_inventory_store_quarter.sql` gives the fund by quarter by store matrix (75 rows); `q_inventory_field_quarter.sql`
gives the full grain the brief asks for, store by fund by quarter by field. Largest fund-quarters: BCRED 2022-12-31
837 (832 by context), BCRED 2022-09-30 192, Apollo 2026-03-31 162, Apollo 2024-06-30 156, Ares 2025-03-31 152 (106
add_row).

### 1.4 Fields, by store, with the seed step

`q_inventory_fields.sql` (88 field-by-store rows); seed `seeds/correction_field.csv` (51 rows, keyed by field and
store pattern). 46 distinct field names are loaded: 29 in the stores loaded before (the brief's figure of 37 is not
reproduced; see 1.7), 17 added by the agent stores (`interest_rate_cash` from B2 and 16 position fields of `row_add`:
`source`, `entity_name`, `canonical_name`, `is_subsidiary`, `axis_profile`, `filing_date`, `bdc_form_type`,
`bdc_investment_identifier`, `bdc_dimensions_raw`, `source_row_id`, `fair_value_currency`, `lien_position`,
`fair_value_source`, `cost_source`, `principal_amount_source`, `shares_held_source`). The four keys that locate a
position (`cik`, `report_date`, `accession_number`, `src_context_id`) are the correction's key, not fields.

By kind and step (`q_inventory_step_summary.sql`):

| Kind | Step | Corrections | row_corrections | by_context | wrapper | agent | withdrawals |
|---|---|---:|---:|---:|---:|---:|---:|
| value | filed | 64 | 0 | 0 | 64 | 0 | 0 |
| value | converted | 461 | 344 | 117 | 0 | 0 | 20 |
| value | reading_input | 545 | 250 | 292 | 0 | 3 | 188 |
| value | companion | 734 | 398 | 336 | 0 | 0 | 0 |
| value | deferred | 2,174 | 421 | 1,753 | 0 | 0 | 355 |
| add_row | converted | 28 | | | | 28 | |
| add_row | companion | 20 | | | | 20 | |
| add_row | deferred | 164 | | | | 164 | |
| relabel | deferred | 202 | | | 202 | | |
| exception | deferred | 3 | | | 3 | | |
| evidence | deferred | 16 | | | 16 | | |

Against the plan's A3 (value corrections of the pre-existing stores): spine numeric 1,022 = filed 64 + converted 461
+ reading_input 542 (row stores) less the 45 `interest_rate_kind`, which the plan counted as companion and the brief
puts at `reading_input`; companion 780 = 734 + those 45 + 1 `maturity_precision`, which the brief puts at `deferred`;
not held 2,173 = 2,174 less that 1. Withdrawals 563, as in the plan.

Steps, as the brief sets them: `filed` for the wrapper untagged values (production fills them at parse time);
`converted` for row-store amounts and maturity (production replaces the published value); `reading_input` for
`interest_rate`, `pik_rate`, `basis_spread` (this layer's `spread`), `interest_rate_kind` (this layer's `rate_kind`
column) and `interest_rate_cash`; `companion` for `principal_amount_currency`, `principal_fx_rate_to_usd`,
`principal_fx_status`, `cost_currency` (and `fair_value_currency`, see 1.6); `deferred` for every field this layer does
not hold.

**Is the dollar principal computed again after a row correction?** No. `principal_amount_usd` is assigned once, in
staging: `pipeline/staging_bdc.py` lines 3074-3081 (`CASE ... END AS principal_amount_usd`, principal times the FX
rate), before `_apply_row_corrections` (unified_holdings.py line 1532). That function sets only the corrected field
(`df.loc[mask, field] = value`, line 2452); the only other writes after it are the agent stores and
`financial_finalization.prepare_artifact` (line 1643), and neither `financial_finalization.py` nor
`financial_conventions.py` names a principal column. (unified_holdings.py line 1355 empties it for equity classes,
before the corrections.) So a corrected principal does not re-run `to_usd`: row-store `principal_amount` and
`principal_amount_usd` are step `converted`, which is why the stores set the dollar principal explicitly on most rows
(108 + 96, with 107 + 95 FX-rate corrections beside them).

### 1.5 How each key becomes a target (built in Task 3)

`q_inventory_key_resolution.sql`, `q_inventory_agent_targets.sql`.

Context keys, by the context's role here:

| Store | Kind | position | not_schedule | unresolved |
|---|---|---:|---:|---:|
| row_corrections_by_context | value | 2,488 | 2 | 8 |
| wrapper (untagged values) | value | 5 | 44 | 15 |
| wrapper | relabel / exception / evidence | 202 / 3 / 14 | 0 | 0 / 0 / 2 |
| agent_investigate_rules | add_row | 0 | 212 (8 positions) | 0 |

Identifier keys (row_corrections, 1,413):

| Fund | native one | native several | native none | of which production one | production several |
|---|---:|---:|---:|---:|---:|
| Ares | 189 | 0 | 6 | 6 | 0 |
| BCRED | 17 | 1 | 0 | | |
| Blue Owl | 148 | 2 | 21 | 20 | 1 |
| Apollo | 851 | 0 | 1 | 1 | 0 |
| HPS | 138 | 0 | 39 | 39 | 0 |
| Total | 1,343 | 3 | 67 | 66 | 1 |

Production's row by accession and identifier, over all 1,413: exactly one 1,407, several 6, none 0 (as in A4). The
plan's A4 splits the 67 as Blue Owl 21, HPS 42, Ares 6, Apollo 1, which sums to 70; measured HPS is 39 and the total
67 agrees. One Blue Owl correction with no native match finds several production rows: the bridge cannot pick one
row for it (Task 3).

- `row_corrections` (identifier key): the position here with the same accession and identifier label; where none,
  production's holdings row with the same accession and identifier gives its `src_context_id` (the
  `production_bridge`, decision 2, a named debt).
- `row_corrections_by_context`, wrapper entries: (accession, context id) directly.
- `agent_investigate_rules` `add_row`: (accession, `src_context_id`) of each position. All 8 contexts are
  `not_schedule` here (the issuer-axis context that carries cost and fair value; the position's quantity is on the
  preceding context, as the rule's own evidence says) and each has exactly one production row. Task 3 decides how an
  `add_row` group makes a position of a context the role rules left out (step `row`).
- `agent_b2_corrections` value leaf: the production row id `ROW-62c19264d44492af` is in `stg_holdings` once, at
  accession 0001287750-26-000006 context c-1095, a `position` here. The key is resolved through production's holdings
  file, like the bridge.

No key needs printed text. Every `row_add` position has a `src_context_id`.

### 1.6 What the agent B2 applier sets (`pipeline/agent_b2_appliers.py` `apply_all_pik_normalization`, lines 280-307)

On the rows its `row_selector` picks: `pik_rate` = template `pik_rate` when given; when `set_interest_to_cash` is true
and `cash_rate` is given, `interest_rate` = `cash_rate` and `interest_rate_kind` = `cash`. Nothing else. Production
stores `interest_rate` as a cash-leg observation there; its financial step then derives the all-in rate from cash plus
PIK. The loader maps the three to this layer's names: `pik_rate` 14.0, `interest_rate_cash` 0.0 (production's
`interest_rate` under kind `cash`), `interest_rate_kind` `cash`. All three are fields this layer holds. A
`cash_rate` without `set_interest_to_cash` is a LoadError (production ignores it).

### 1.7 Counts that differ from the plan or brief

| Count | Plan / brief | Measured | Why |
|---|---|---|---|
| Field names in the loaded stores | 37 (brief, "appendix A3") | 29 before the load, 46 after | A3 lists no total; 29 is the count in `stg_correction` at 8dc29093 (`q_inventory_pre_fields.sql`); the agent stores add 17. Where 37 came from is not known |
| A3 family split | spine 1,022, companion 780, not held 2,173 | 1,067 / 734 / 2,174 | step assignment only (45 `interest_rate_kind`, 1 `maturity_precision`); see 1.4 |
| A4 identifier keys with no native match, HPS | 42 (fund split sums to 70) | 39 (total 67, as A4) | the plan's per-fund split does not add up to its own total |
| Every other count of A1, A2, A4, the brief's key shapes, 108+96 and 107+95 | | equal | |

### 1.8 Proofs

- Loader output (production stores): correction 4,411 rows (add_row 212, evidence 16, exception 3, relabel 202, value
  3,978), correction_rule 13, reading_rule 156, not_loaded 3, rule_label_example 45, wrapper_drift 5; agent store
  files of the five funds 24, skipped 8.
- Snapshot (every base table plus seven named views, before at 8dc29093 and after this task): no table changed. The
  only differences are `stg_correction` (every correction_id rehashed by the new columns; compared on every other
  column, the 4,196 earlier rows are identical, `q_t2_snapshot_stg_correction.sql`; 215 agent rows added) and
  `stg_readings_manifest` (loader version 6, one more table). `correction_field` is new.
- Build `PASS=732 WARN=106 ERROR=0 TOTAL=838` (8dc29093: 704 / 106 / 810; 28 new nodes, all pass; no warning
  count moved).

## 2. Outcomes of the corrections on amounts and on the row set (slice 5 Task 3)

Measured 2026-11-24 on the build of this task (branch `warehouse-slice5`). Models and rules: `intermediate_spine.md`
section 6.5. Queries: `warehouse/scripts/slice5/q_t3_*.sql`. Rates are not applied here: every rate correction is
`deferred|rate_reading_not_rerun` until Task 4. Applying production's corrections makes the two pipelines agree; it does
not check a correction against the filing.

### 2.1 Outcomes per store and fund (target rows; `q_t3_outcomes.sql`)

| Store | Outcome | Reason | Ares | BCRED | Blue Owl | Apollo | HPS | Total |
|---|---|---|---:|---:|---:|---:|---:|---:|
| agent_b2_corrections | deferred | rate_reading_not_rerun | 3 | | | | | 3 |
| agent_investigate_rules | applied | | 16 | | | | | 16 |
| agent_investigate_rules | deferred | field_not_held | 164 | | | | | 164 |
| agent_investigate_rules | no_op | equal_to_normalised | 32 | | | | | 32 |
| row_corrections | applied | | 26 | | 67 | 407 | 119 | 619 |
| row_corrections | deferred | field_not_held | 37 | 16 | 79 | 277 | 13 | 422 |
| row_corrections | deferred | no_companion_column | | | | 106 | | 106 |
| row_corrections | deferred | rate_reading_not_rerun | 130 | 3 | 21 | 56 | 45 | 255 |
| row_corrections | no_op | already_absent | | | 4 | | | 4 |
| row_corrections | no_op | equal_to_normalised | 2 | | 1 | 6 | | 9 |
| row_corrections | rejected | bridge_ambiguous | | | 1 | | | 1 |
| row_corrections_by_context | applied | | | 7 | 127 | 25 | 139 | 298 |
| row_corrections_by_context | deferred | field_not_held | 186 | 925 | 35 | 241 | 366 | 1,753 |
| row_corrections_by_context | deferred | no_companion_column | | 2 | 44 | 3 | 47 | 96 |
| row_corrections_by_context | deferred | rate_reading_not_rerun | | 157 | | | 141 | 298 |
| row_corrections_by_context | no_op | equal_to_normalised | | 41 | 5 | 4 | 3 | 53 |
| wrapper | applied | | 6 | 1 | | 56 | | 63 |
| wrapper | deferred | field_not_held (relabels) | | | 202 | | | 202 |
| wrapper | failed | conversion_unresolved | | | | 1 | | 1 |
| wrapper | no_op | evidence_only | 16 | | | | | 16 |
| wrapper | no_op | procedure_not_built | | | | | 3 | 3 |

Totals (target rows; 4,414 rows for 4,411 corrections, three identifier keys match two positions each): applied 996,
deferred 3,299 (field_not_held 2,541, rate_reading_not_rerun 556, no_companion_column 202), no_op 117
(equal_to_normalised 94, evidence_only 16, already_absent 4, procedure_not_built 3), rejected 1 (bridge_ambiguous),
failed 1 (conversion_unresolved). Rejected for any other reason: 0 (target_not_found, target_not_position, conflict,
expected_value_differs, printed_cell_*). Each pair has its own ceiling (`correction_outcome_max`).

- `failed|conversion_unresolved` (1): an Apollo untagged cost (41,554,000, 2024-06-30). Its filing is listed under the
  fund's sign rule `bracketed_unsigned`, which needs the printed brackets of the value; an untagged value has no
  placement, so the rule is `feature_missing` and the cost stays as before (absent). Not applied, not forced.
- The brief expected about 2,375 deferred (2,173 values and 202 relabels): measured field_not_held 2,541 = 2,174 value
  corrections (Task 2 moved `maturity_precision` to deferred) + 164 agent position metadata + 202 relabels + 1 second
  target of a two-position identifier key.

### 2.2 The production bridge (owner decision 2: a NAMED DEBT)

67 identifier-keyed corrections find no position here by their text and locate their row through production's
holdings file (Ares 6, Blue Owl 21, Apollo 1, HPS 39). **They must be re-keyed by context before this layer can
replace production.** Ceiling 67. Outcomes: applied 20 (Blue Owl 3, HPS 17), deferred 41 (fields not held 22, rates
19), no_op 5, rejected 1: one Blue Owl `shares_held` withdrawal whose production rows name two contexts; the bridge does
not pick one (`bridge_ambiguous`). The 6 Ares and 1 Apollo bridged corrections land on rows held unresolved here (rates
and an industry text, all deferred); the two Ares rows become positions through their wrapper principals (2.4).

### 2.3 The 44 Apollo zero fair values (owner answer of 2026-11-24 on decision 4)

Test (`int_correction_fair_value_cell`): the one table row holding the context's placed facts; cells laid on the grid
by their colspans; the cell covering the grid column where the table's other fair-value facts sit (the commonest). It
prints a dash or a zero when, with white space, `$`, `(`, `)` and `,` removed, it is a single `-`, en dash or em dash,
or a zero in digits. Result: **all 44 print an em dash; 44 applied, 0 not applied** (ceilings 0 on
`printed_cell_not_found` and `printed_cell_not_dash_or_zero`). Unit test `int_correction_fair_value_cell_dash_or_zero`
includes the false cases ('1,576', 'N/A', '12' with a dash in another column, an empty cell, no printed row, two rows).

Rollups (`q_t3_rollups.sql`): the subtotals decided through the fund rule subtotal_on_fair_value with a zero line
beneath them by label: Chemicals Heubach (2024-12-31, 2025-03-31), Media Material+ (same two quarters), Public
Partnerships (five quarters). In all ten, after the zero lines are added, the rollup's fair value and its cost both
equal the sum of the positions beneath (gap 0); the zero lines carry the missing cost (Heubach 9,545,000 and 9,431,000;
Material+ 1,576,000 twice; Public Partnerships 50,000). The rollups stay aggregates. In the other quarters the filing
prints no rollup over these lines (no rule-6 row shares their label).

### 2.4 Contexts corrections make positions (`int_row_corrected`, `q_t3_promotions.sql`)

| Row reason | Contexts | Fund, role | Fair value | Cost |
|---|---:|---|---:|---:|
| correction_supplies_fair_value | 44 | Apollo, not_schedule rule 3 | 0 | 74.7m (the lines' filed cost; corrected in Task 4 from 64.7m, `q_t4_zero_lines_cost.sql`) |
| correction_supplies_term | 8 | Ares 2 (2022-09-30), Apollo 6; unresolved rule 9; a wrapper principal | 319.0m | 283.6m (one cost failed, 2.1) |
| correction_adds_row | 8 | Ares row_add (2025-03-31, 2025-06-30); not_schedule rule 1 | 127.5m (the filed fact) | 145.5m |

Every one has a production row on the published basis (`tests/int_row_corrected_promoted_in_production.sql`, 0) and
the role its reason allows (`tests/int_row_corrected_promotion_rules.sql`; rule 1 is allowed for add_row only).

### 2.5 Published amounts that changed (`q_t3_changed_values.sql`)

| Field | Rows | Of which the value | Change in value |
|---|---:|---:|---:|
| fair_value | 46 | 46 | +3,272,000 (2 Apollo row-store values; the 44 zero lines add 0) |
| cost | 21 | 20 | +250.8m on 6 promoted rows (Ares 145.4m, Apollo 105.4m), +0.4m Ares untagged, -6.3m on 13 Apollo row-store rows; 1 Blue Owl row whose currency alone moved |
| principal_amount | 295 | 17 | 12 promoted rows (+379.7m), 5 filed rows (Ares +52.8m, BCRED +1.9m, Apollo +50.6m); 278 rows whose currency alone moved |
| principal_amount_usd | 218 | | row-store values and the dollar value of corrected principals (the EUR and GBP Apollo principals now convert: +51.7m) |
| shares | 224 | | row-store values and 15 withdrawals |

The 8 Ares add_row fair values and costs equal the filed facts of their contexts (no_op).

### 2.6 Sum check on the corrected basis

The normalised-basis check lists 11 fund-quarters (8 miss the filed total, 3 have none). On the corrected published
basis all 8 tie (Ares 2022-09-30, 2025-03-31, 2025-06-30; Apollo 2023-09-30, 2024-06-30, 2024-09-30, 2025-03-31,
2026-03-31): only the three 2026-09-30 quarters without a filed total remain (ceiling 3, pinned set). That the totals
tie shows the added rows close the gap; it does not show each row's value is right.

## 3. Corrections on rates, and the adjacent rate context (slice 5 Task 4)

Measured 2026-11-25 on the full build (`PASS=806 WARN=131 ERROR=0 TOTAL=937`; 175 Python tests). Agreement with
production is not correctness: the reading re-runs production's corrections, it does not check them.

### 3.1 Outcomes of the 556 rate corrections (`q_t4_outcomes.sql`)

Task 3 held these as deferred, `rate_reading_not_rerun`; that pair is gone from the closed list.

| Field | Applied | No-op, equal | No-op, already absent | Failed, `rate_reading_unresolved` |
|---|---:|---:|---:|---:|
| interest_rate | 56 | 2 | 0 | 7 |
| interest_rate_cash | 1 | 0 | 0 | 0 |
| rate_kind | 17 | 29 | 0 | 0 |
| pik_rate | 160 | 1 | 3 | 0 |
| spread | 267 | 0 | 2 | 0 |
| maturity_date | 11 | 0 | 0 | 0 |
| Total | 512 | 32 | 5 | 7 |

All corrections after this task: applied 1,508, deferred 2,743 (field not held 2,541, no companion column 202), no-op
154, failed 8, rejected 1.

How a rate correction is applied: a corrected rate, cash-pay rate, PIK rate or kind replaces that input and the rate
reading (macro `rate_reading`) runs again on the corrected inputs (`int_rate_corrected_input`, `int_rate_corrected`);
the all-in rate, cash leg and kind are its output. A corrected spread or maturity replaces the converted value. A row
whose corrected reading fails the legs check is failed and keeps its values as before.

The 7 failed: Blue Owl, one position in seven filings (rate 12.0 corrected onto a row with a 6.0 PIK rate and no fund
rate reading). No rule reads the corrected rate, so the row is kept as before. Failed for `legs_do_not_add`,
`pik_above_rate`, `kind_not_decidable`: 0 each (ceilings 0).

### 3.2 Published rate rows a correction changed (`q_t4_rate_changed.sql`)

| Field | Rows | Detail |
|---|---:|---|
| interest_rate | 59 | 44 corrected, 15 withdrawn |
| interest_rate_cash | 154 | 1 corrected cash-pay input, 144 legs derived again, 9 left absent by a withdrawn rate |
| pik_rate | 160 | 147 corrected, 13 withdrawn |
| spread | 128 | 111 converted, 14 withdrawn, 1 derived again, 2 left `text_not_read` (a corrected PIK rate makes the row need the printed total margin) |
| maturity_date | 9 | 9 converted |

### 3.3 Against production's values (`q_t4_needs_correction.sql`, `q_t4_needs_correction_left.sql`)

Of the published rate rows `cmp_rate` calls `needs_correction` (it still reads the normalised values; Task 5 moves it):

| Field | Rows | Equal to production after correction |
|---|---:|---:|
| interest_rate | 51 | 50 |
| interest_rate_cash | 68 | 64 |
| rate_kind | 45 | 44 |
| pik_rate | 158 | 158 |
| spread | 123 | 123 |
| maturity_date | 9 | 9 |

The 6 left, all HPS, for Task 5 to give a cause:

- 0001838126-25-000017 c-157 (rate, cash leg, kind): production reads the 13.5 spread tag as a fixed coupon
  (`interest_rate:from_spread_tag`), a reading this layer does not have. The PIK correction is applied.
- Three cash legs (0001628280-26-020206 c-934, 0001628280-26-033248 c-912, 0001838126-25-000073 c-903): this layer sets
  the cash leg equal to the all-in rate (owner ruling A); production leaves it empty.

### 3.4 The adjacent rate context (`int_rate_adjacent`, `q_t4_adjacent.sql`, `q_t4_adjacent_production.sql`)

Owner decision 5: built as a structural rule (action `adopt_adjacent_rate_context`), selected by the fund's wrapper
declaration, never a list of contexts. 7 pairs, all Ares (ceiling 7), as the slice 4 approximation counted.

| Quarter | Taker | Giver | Facts taken | Against production |
|---|---|---|---|---|
| 2023-12-31 | c-1206 | c-1205 | rate, PIK, spread | all equal |
| 2025-03-31 | c-1728 | c-1727 | rate, PIK, spread | values equal; production keeps the giver's context id (row-set pair below) |
| 2025-06-30 | c-1268 | c-1267 | PIK only | PIK equal; rate empty here (`text_not_read`, as every PIK-only row), production 10.25 |
| 2025-06-30 | c-1446 | c-1445 | rate, spread | equal; cash leg set here, empty in production (owner ruling A) |
| 2025-06-30 | c-1776 | c-1775 | rate, PIK, spread | values equal; production keeps the giver's context id |
| 2025-09-30 | c-1475 | c-1474 | rate, spread | equal; cash leg set here, empty in production |
| 2025-09-30 | c-165 | c-164 | rate, spread | equal; cash leg set here, empty in production |

The two pairs where production keeps the giver's context id are the 2 new-only and 2 production-only
`rate_only_context_pair` rows of `cmp_row_set`, which did not change. Ceilings raised for the takers, each row named in
`dbt_project.yml`: `text_not_read` +1 on rate, cash leg and spread (c-1268); cash equals all-in +3 (31,239 to 31,242).
The printed rows of the pairs were not opened.

HPS whole-coupon PIK: not built (needs printed text and the loan class; text spec). The 3 wrapper entries stay `no_op`,
`procedure_not_built`.

### 3.5 Proofs

Snapshot before the task against the build after it (`scripts/slice5/compare_snapshots.py`, 43 relations): 32
unchanged, among them `cmp_amount`, `cmp_row_set`, `int_amount_normalised`, `int_source_row`, `fact_observation`.
Changed: seeds `action_field` and `reading_action` (+1 row each, the new action) and `correction_field` (spread is
`converted`); `int_correction_screen` and `int_correction_application` (the 556); `int_correction_target` (269, the
spread step name); `int_row_corrected` (2 Ares rows, correction ids only); `int_field_corrected` 714 rows, all rate
fields (rate 75, cash leg 176, PIK 164, spread 288, maturity 11; no amount row); `int_field_normalised` and
`int_rate_normalised` 25 rows, all on the 7 takers; `cmp_rate` 22 rows, the takers
(`q_t4_field_corrected_diff_fields.sql`).
