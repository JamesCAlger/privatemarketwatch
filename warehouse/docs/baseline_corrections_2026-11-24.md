# Baseline: corrections (slice 5), 2026-11-24

Section 2 is written by Task 3 (the outcomes of applying the corrections to amounts and to the row set), section 3
by Task 4 (rates), section 4 by Task 5 (the comparison with production on the corrected values), section 5 by Task 6
(measurements for a later consolidation of corrections into filer rules). Nothing in section 1 applies a correction; it says what the stores hold, what the loader
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

### 3.6 After the review (2026-11-25)

Independent review: approved with minors; it reproduced sections 3.1 to 3.4 and the 7 pairs with its own query.

- Rows corrections moved away from production (left out of 3.3): 8 cash legs and 2 spreads matched production before
  correction and differ after. Over all corrected rows 17 cash legs differ from production, every one set equal to the
  all-in rate under owner ruling A where production leaves it empty. The task's stop condition (more than 10 corrected
  rows whose cash leg or kind differs with no production rule to explain it) is not met only because ruling A is the
  explanation.
- The 2 spreads (Apollo 0000950170-24-031479 C_1de7bac0, 0000950170-24-058684 C_a98dfaae): a corrected PIK rate makes
  the row one whose spread rule needs the printed total margin, so the spread goes from 4.5 to `text_not_read`, as on
  every filed row with a PIK rate and that rule. Production keeps 4.5. A named difference for Task 5 and an owner
  item: keep the spread as before when only the PIK rate is corrected, or leave it unread like its filed peers. The
  test `int_field_corrected_never_erase` was loosened by an exception for these rows.
- Ceilings for `rate_only_context_not_adopted` lowered to the measured counts: rate 2, kind 2, cash leg, PIK and
  spread 0 (`q_t4_not_adopted_left.sql`). The rows left: Ares 0001287750-25-000038 c-1268 (adopted; the difference is
  the PIK-only reading; the detail is stale) and Ares 0001287750-25-000007 c-1544 (production has a rate 9.23; the
  structural rule finds no pair in that filing; not examined). Both for Task 5.
- The pairing reads the trailing digits of the context id. Run on every fund with no rule filter it finds one
  spurious Apollo pair between two UUID context ids; production's rule has the same flaw. Harmless while only Ares
  declares the rule; check before a fund with UUID context ids declares it.

## 4. The comparison on the corrected values, and the BCRED trace (slice 5 Task 5)

Measured 2026-11-25 on the build of this task (branch `warehouse-slice5`). Queries: `warehouse/scripts/slice5/q_t5_*.sql`.
Before = the build at da17b7e9 (snapshot `scratch/2026-11-25_slice5_t5/snap`, `*_before.parquet`). Agreement with
production shows that the two pipelines apply the same corrections the same way. It does not show a correction is right.

### 4.1 What changed in the three comparison models

A comparison model (`cmp_*`) is a table that sets this layer beside production row by row and gives every difference a
cause from the closed list.

- `cmp_row_set` reads the corrected row set (`int_row_corrected`) instead of the filed one (`int_source_row`). The
  features that explain a one-sided row (role, rule, reason, cash flags) are still those of `int_source_row`. New
  columns: `row_reason`, `row_correction_ids`, `production_context_id`. This layer's total for the filed-total tie is the
  corrected fair value.
- An adopted rate-only pair (`int_rate_adjacent`, Task 4) whose production row keeps the giver's context id: where
  production has a row at the giver and none at the taker, its row is compared with this layer's taker.
  `production_context_id` keeps production's id; `cmp_amount` and `cmp_rate` join production on it. A pair rule, not a
  list. It joins the 2 Ares pairs of section 3.4 (c-1728 / c-1727, c-1776 / c-1775).
- `cmp_amount` and `cmp_rate` read `int_field_corrected` instead of `int_field_normalised`. New columns:
  `value_normalised` (the value before corrections; `currency_normalised` for the currency, `date_normalised` and
  `text_normalised` for maturity and kind in `cmp_rate`) and `correction_id`.
- The old correction causes are gone: `needs_correction|correction_loaded_applied`, `needs_correction|correction_loaded`,
  `not_yet_explained|correction_loaded_value_not_matched`, `not_yet_explained|correction_loaded_not_named`, and in
  `cmp_row_set` `needs_correction|correction_supplies_value_or_term`. Corrections are now read from
  `int_correction_application` (the outcome of each correction on its target). New rules, each with a unit test row
  that takes it and one that must not:

| Model | Cause and detail | Rule |
|---|---|---|
| cmp_amount, cmp_rate | `needs_correction|correction_<outcome>_<reason>` | covering corrections are loaded on the row and none is used here (rejected, failed or deferred) |
| cmp_amount, cmp_rate | `not_yet_explained|correction_applied_value_differs` | a correction applied on the field, production holds another value, no other rule says why (checked last) |
| cmp_amount | `convention|untagged_principal_currency_blank_in_production` | the currency of a principal set at step filed by a correction with no unit, production's currency empty |
| cmp_amount | `convention|filled_principal_currency_blank_in_production` (since Task 6 Part A: `old_wrong`, section 4.6) | production's dedupe filled the principal from a sibling context (src_filled_fields) and left its currency empty |
| cmp_rate | `owner_review|pik_correction_leaves_spread_unread` | a PIK correction applied makes the spread text_not_read while the value before equals production's |
| cmp_rate | `needs_store_not_loaded|same_identifier_context_fill_not_built` | production filled the rate (src_filled_fields), the row is no taker here, and a context of the filing with the same label carries a rate fact and no fair value |
| cmp_rate | `needs_store_not_loaded|rate_only_context_not_adopted` (changed) | now only where the row is not a taker this layer paired |
| cmp_row_set | `needs_correction|correction_not_promoted` | a correction on a production-only row that did not make it a position (renamed from the old detail; 0 rows) |

The `cmp_rate` comment that said the adjacent rule is "not built here" is corrected.

### 4.2 Before and after

Re-measured before on the current build: every `needs_correction` count equals the brief's 2026-11-24 starting
count. `rate_only_context_not_adopted` was already down to rate 2, kind 2 (Task 4; the brief's rate 6, cash 1, PIK 2,
spread 4, kind 6 are from before Task 4).

`cmp_row_set` (one-sided rows):

| Basis, side | Cause and detail | Before | After |
|---|---|---:|---:|
| published, production only | needs_correction, correction_supplies_value_or_term | 52 | 0 |
| published, production only | needs_store_not_loaded, production_row_added | 8 | 0 |
| published, both sides | needs_store_not_loaded, rate_only_context_pair | 4 (2 + 2) | 0 |
| published, new only | convention, cash_published_d7_seed_pattern | 31 | 31 |
| published, new only | not_yet_explained, none / relabel_loaded | 1 / 1 | 1 / 1 |
| unpublished, new only | convention (two details) | 30 | 30 |

62 rows are on both sides since this task: 44 Apollo zero lines and 8 term contexts (corrections make them
positions), 8 Ares add_row positions, 2 adopted pairs.

`cmp_amount`, published (unpublished unchanged):

| Field | Cause and detail | Before | After |
|---|---|---:|---:|
| fair value | needs_correction (both details) | 2 | 0 |
| cost | needs_correction (both details) | 14 | 0 |
| cost | needs_correction, correction_failed_conversion_unresolved | 0 | 1 |
| principal | needs_correction (both details) | 5 | 0 |
| principal | not_yet_explained, principal_empty_class_not_equity | 14 | 14 |
| currency | needs_correction (both details) | 282 | 0 |
| currency | convention, count_principal_currency_blank_in_production | 671 | 671 |
| currency | convention, untagged_principal_currency_blank_in_production | 0 | 3 |
| currency | convention, filled_principal_currency_blank_in_production | 0 | 2 |
| dollar principal | needs_correction (both details) | 194 | 0 |
| dollar principal | not_yet_explained, correction_loaded_value_not_matched | 2 | 0 |
| dollar principal | not_yet_explained, principal_empty_class_not_equity | 14 | 14 |
| shares | needs_correction, correction_loaded_applied | 219 | 0 |
| every field | owner_review, old_wrong | unchanged | unchanged |

`cmp_rate`:

| Basis | Field | Cause and detail | Before | After |
|---|---|---|---:|---:|
| published | rate | needs_correction | 51 | 0 |
| published | rate | identifier_text_not_read | 73 | 77 |
| published | rate | printed_rate_type_and_loan_class_not_read | 405 | 406 |
| published | rate | printed_reference_rate_column_not_read | 112 | 113 |
| published | rate | production_corrected_no_loaded_store | 1 | 0 |
| published | rate | rate_only_context_not_adopted | 2 | 0 |
| published | rate | same_identifier_context_fill_not_built | 0 | 1 |
| published | cash leg | needs_correction | 68 | 0 |
| published | cash leg | convention, cash_equals_all_in_owner_ruling | 31,242 | 31,254 |
| published | cash leg | identifier_text_not_read | 52 | 56 |
| published | cash leg | printed_pik_not_read | 67 | 3 |
| published | cash leg | printed_reference_rate_column_not_read | 76 | 77 |
| published | cash leg | production_corrected_no_loaded_store | 1 | 0 |
| published | PIK rate | needs_correction | 158 | 0 |
| published | spread | needs_correction | 123 | 0 |
| published | spread | identifier_text_not_read | 19 | 25 |
| published | spread | printed_total_margin_not_read | 479 | 478 |
| published | spread | owner_review, pik_correction_leaves_spread_unread | 0 | 2 |
| published | maturity | needs_correction | 9 | 0 |
| published | maturity | identifier_text_not_read | 1 | 7 |
| published | maturity | printed_maturity_not_read | 43,996 | 44,000 |
| published | kind | needs_correction | 45 | 0 |
| published | kind | as rate (identifier text 77, printed rate type 406, reference column 113, not adopted 0, same identifier 1, production corrected 0) | | |
| unpublished | spread | needs_correction | 142 | 0 |
| unpublished | maturity | needs_correction | 2 | 0 |

`not_yet_explained` and `new_wrong`: 0 on every field and basis except the 14 + 14 BCRED rows (unchanged, own detail
ceiling, section 4.4) and the 2 `cmp_row_set` rows (unchanged). `needs_correction`: 0 everywhere except the one Apollo
cost. No published fair value, cost or principal that was equal before this slice differs now
(`q_t5_cause_moves.sql`: no equal row on those fields gained a cause).

### 4.3 The rows behind each change (all opened)

Former needs_correction rows (`q_t5_amount_explore.sql`, `q_t5_rate_explore.sql`): amounts 716, all equal after
correction, including the 2 Apollo dollar principals of `correction_loaded_value_not_matched`, which now convert through
`to_usd` on the corrected EUR / GBP principal. Rates: 454 published and 144 unpublished; all equal or both empty
except HPS 0001838126-25-000017 c-157 (rate, cash leg, kind) and three HPS cash legs.

Every open row whose field carries an applied correction (`q_t5_applied_open.sql`, 22 rows, all opened):

| Rows | Cause | Why |
|---|---|---|
| 3 currency rows: Ares 0001287750-22-000052 i37db8a34... and i6cfa6b6a... (2022-09-30), 0001287750-23-000010 ie6a91f4a... (2022-12-31) | convention, untagged_principal_currency_blank_in_production | wrapper untagged principals with no unit (e.g. 52,800,000). Production fills them at parse time with no unit, so its currency is blank (dollar principal 52.8m, equal); this layer writes USD |
| 17 cash legs (Ares c-1046, c-1047, c-1048, c-1051, c-752, c-765; Apollo C_039efe54, C_b66364fa, C_18280e10, C_0aeabb67, C_4b74c7c2, C_53b7bfb4, C_9b863965; HPS c-934, c-912, c-922, c-903) | convention, cash_equals_all_in_owner_ruling | owner ruling A: the cash leg is the all-in rate where no PIK rate is read; production leaves it empty. The rate itself equals production's on every one |
| 2 Apollo spreads (0000950170-24-031479 C_1de7bac0, 0000950170-24-058684 C_a98dfaae) | owner_review, pik_correction_leaves_spread_unread | value before 4.5 = production 4.5; the corrected PIK rate makes the row's spread rule need the printed total margin. Owner item: keep the spread as before when only the PIK rate is corrected, or leave it unread like its filed peers |

No row reaches `correction_applied_value_differs` (0 on every field).

Carried items from Task 4 (`q_t5_carried.sql`):

- HPS c-157: rate (production 13.5), cash leg (7.15) and kind: `needs_store_not_loaded|printed_reference_rate_column_not_read`.
  Production's src_transforms has `interest_rate:from_spread_tag;basis_spread:fixed_coupon`: it read 'no reference
  rate' in the printed column and moved the 13.5 spread tag to the rate. This layer has no such reading. The PIK
  correction (6.35) is applied and equal. The existing detail names the mechanism exactly; ceilings +1.
- The three HPS cash legs (c-934, c-912, c-903): `convention|cash_equals_all_in_owner_ruling`; the corrected rate is
  equal (9.36, 9.17, 9.81).
- The two Apollo spreads: as above.
- Ares 0001287750-25-000038 c-1268: now `printed_rate_type_and_loan_class_not_read` on rate and kind, as every PIK-only
  row. The rule `rate_only_context_not_adopted` now skips a taker this layer paired. PIK 10.25 equal.
- Ares 0001287750-25-000007 c-1544: `needs_store_not_loaded|same_identifier_context_fill_not_built` (rate, kind). Read
  production's row and contexts c-1538 to c-1550 (`q_t5_c1544.sql`): c-1543 has the same label ("Rawlings Sporting Goods
  ... First lien senior secured loan"), carries only the rate fact 0.0923 and no fair value; c-1544 carries the spread,
  fair value and principal and no rate. Production's `adopt_rate_only_contexts` does not pair them (its taker must
  have no rate field; c-1544 has a spread), but its dedupe (`pipeline/bdc_filings.py` `_deduplicate_bdc_holdings`,
  lines 1231-1393) groups rows by identifier and fills a missing value from a sibling row: src_filled_fields
  `interest_rate`. This layer's structural rule needs a taker with no rate fact, so it does not take the rate.
- The 7 failed Blue Owl rate corrections: rate, cash leg and kind both empty (production has no rate either); PIK
  6.0 equal. No cause needed.

Rows on both sides since this task (`q_t5_new_both_open.sql`, all 40 open rows opened):

| Rows | Cause | Note |
|---|---|---|
| fair value, principal, dollar principal, shares, share of net assets on all 62 rows | equal | the 8 add_row positions are equal on every field |
| Apollo 0000950170-24-094137 C_f9b16d68 cost (production 41,554,000) | needs_correction, correction_failed_conversion_unresolved | the untagged cost this layer cannot sign without its print (section 2.1). Production applies it |
| Ares 2022-09-30 two term contexts, currency | convention, untagged_principal_currency_blank_in_production | as above |
| Ares c-1728, c-1776 (pairs), currency | convention, filled_principal_currency_blank_in_production | production's row is the giver's (c-1727, c-1775); its dedupe filled cost, fair value and principal from the taker (src_filled_fields) without the unit, so the currency is blank and the dollar principal equals the principal |
| 4 Apollo zero lines: rate, cash leg, kind | identifier_text_not_read | production reads 10.43 from the identifier text |
| 7 Apollo zero lines: cash leg | convention, cash_equals_all_in_owner_ruling | ruling A |
| 6 Apollo term contexts: spread, maturity | identifier_text_not_read | production reads them from the identifier text |
| Ares 2022-09-30 two term contexts, c-1728, c-1776: maturity | printed_maturity_not_read | production reads the date from the printed row |

Every row added to a raised detail ceiling is listed by `q_t5_rate_added_rows.sql`; the cash-leg convention moved
31,242 -> 31,254: +3 HPS (were needs_correction), +8 cash legs a correction now sets (Ares c-1047, c-1051, c-752,
c-765; Apollo C_039efe54, C_b66364fa, C_0aeabb67; HPS c-922), +7 Apollo zero lines, -6 cash legs now both empty (a
withdrawn rate: Apollo C_6d0842cd, C_7b0708ee, C_3ec10678, C_ae5fc255, C_dc8a4e86; Ares c-764).

### 4.4 BCRED trace (owner decision 2026-11-23)

Work time: 11:43 to 11:45 on 2026-11-25 by the session clock (well inside the 60-minute limit). The 14 rows
(`q_t5_bcred_rows.sql`): BCRED 2025-06-30 to 2026-06-30, labels "<vehicle> - Units" (Regatta Kilo, HPS Freshwater
Warehouse Parent, Pikes Peak Bravo, Balboa Bay Loan Funding 2025-3); production class STRUCTURED_CREDIT, asset category
EQUITY_COMMON, principal and dollar principal empty, currency USD kept, no correction, src_transforms has no
`principal_amount:from_shares_tag`.

Found. The step and its condition:

1. `pipeline/classification.py` `_sql_classify_bdc_asset` (lines 440-453): the instrument text "Units" matches the
   equity keyword list `_BDC_EQUITY_KEYWORDS` (line 152, "units") before the field heuristic, so asset_category is
   EQUITY_COMMON. `_sql_classify_index` (line 531): EQUITY_COMMON and a corporate issuer gives COMMON_EQUITY.
2. `pipeline/unified_holdings.py` lines 1346-1355, in the class step (`_index_class`, line 1232): `CASE WHEN
   _index_class IN ('COMMON_EQUITY', 'PREFERRED_EQUITY', 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
   'REAL_ESTATE_FUND', 'HEDGE_FUND') THEN NULL ELSE principal_amount END` (and the same for principal_amount_usd). The
   currency is not emptied, which is the signature seen.
3. `pipeline/printed_sections.py` `apply_structured_sections` (lines 135-140), called later at unified_holdings.py line
   1529: rows printed under the BCRED heading "Structured Finance Obligations" (wrapper
   `dispatch.structured_credit_sections`, `structured_re`) are set to index_classification STRUCTURED_CREDIT. BCRED's
   wrapper has no `equity_re`, so asset_category stays EQUITY_COMMON from step 1. Nothing restores the principal
   ("principal is left as it is", line 149).

So production empties the principal under its first class and then re-classes the row, the same pattern as
`old_wrong|principal_emptied_then_reclassified` (there the re-class is a correction). The only principal-emptying
statement in the production code read (unified_holdings.py, printed_sections.py, financial_finalization.py,
financial_conventions.py, agent_promoted.py, agent_rule.py, holdings_finalizer.py) is lines 1350 and 1355.

Not verified: that each of the 14 rows had `_index_class` COMMON_EQUITY at line 1232 (not run; inferred from the label
word and from the principal being empty while that is the only emptying step), and that each sits under the
structured heading on its page (inferred from the final class STRUCTURED_CREDIT, which the class step would not give
these labels).

Cause: **waits for a controller ruling** between `old_wrong` (production's emptying is an ordering side effect: its own
final class is not one it empties), `owner_review` (the rows are CLO equity units; owner decision D17 says a principal
that is a unit count on an equity class is to be empty; whether the "Par Amount/Units" tag here is a par or a unit
count is that question) and `convention`. Recommendation: `owner_review`, detail
`principal_emptied_before_section_reclass`, beside D17, because production's result (no principal on an equity
tranche) may be right for the wrong reason, and only the owner can say whether these units are a par. Until the
ruling the rows keep `not_yet_explained|principal_empty_class_not_equity`, now under a detail ceiling of their own (14
each), so the not_yet_explained cause ceiling is 0 on every field.

**Ruling (controller, 2026-11-25, Task 6 Part A).** The 14 + 14 rows are now `owner_review`, detail
`principal_emptied_before_section_reclass`, with a detail ceiling of 14 on principal and 14 on dollar principal. The
`not_yet_explained|principal_empty_class_not_equity` detail and its ceilings are gone. The owner question is the one
above, next to D17: is a CLO equity "Units" amount a par or a unit count?

What the trace established: the step that empties the principal (the file and lines in points 1 to 3). What no run
established:

- each row's first class (COMMON_EQUITY is inferred, not observed);
- whether the later re-class to STRUCTURED_CREDIT comes from the printed section (`apply_structured_sections`) or from
  `_stabilize_classification` / `_restore_deterministic_classification_rules` (`pipeline/unified_holdings.py` lines
  1519-1520), which run near the same point. The outcome for these rows is the same either way; the mechanism name is
  not proven.

### 4.5 Proofs

- Snapshot before the task against the full build after it (`scripts/slice5/compare_snapshots.py`, 47 relations): every
  `int_*` table, `int_field_normalised`, the dimensions, facts and seeds unchanged (0 / 0). Changed: `cmp_amount`
  (499,905 -> 500,339 rows: +434 = 62 rows x 7 fields, causes moved), `cmp_rate` (428,490 -> 428,862: +372 = 62 x 6),
  `cmp_row_set` (71,542 -> 71,540: 64 one-sided rows became 62 rows on both sides).
- Full build `PASS=827 WARN=115 ERROR=0 TOTAL=942` (before: 806 / 131 / 0 / 937; 5 new detail tests; warnings fall
  because the needs_correction tests now count 0). Python tests 175 passed.
- Unit tests: `cmp_row_set_catch_all_causes`, `cmp_row_set_early_causes`, `cmp_amount_cause_rules`,
  `cmp_rate_cause_rules` updated to the new inputs, with new rows for each new rule and its false case.

### 4.6 Review fixes (slice 5 Task 6 Part A, 2026-11-25)

The Task 5 review approved with minors. These fixes change labels and tests only; no value of this layer changes.

| Fix | What changed | Rows |
|---|---|---:|
| 1 | The 14 BCRED rows: `not_yet_explained|principal_empty_class_not_equity` becomes `owner_review|principal_emptied_before_section_reclass` (controller ruling; section 4.4). Detail ceiling 14 on principal and 14 on dollar principal; the old detail and its ceilings go | 14 + 14 |
| 2 | `filled_principal_currency_blank_in_production` moves from `convention` to `old_wrong` (controller ruling): production's dedupe copied the value without its unit. Ares c-1728, c-1776. Detail ceiling 2 kept | 2 |
| 2 | `convention|untagged_principal_currency_blank_in_production` stays, listed as **unverified**: both pipelines assume USD for a principal with no unit, and no filing print was read to confirm it | 3 |
| 3 | Own detail ceilings for `needs_correction|correction_failed_conversion_unresolved` (cost, 1; the Apollo cost C_f9b16d68) and `owner_review|pik_correction_leaves_spread_unread` (spread, 2). The cost `needs_correction` and spread `owner_review` cause ceilings go from 1 and 2 to 0 | 1, 2 |
| 4 | Unit test `cmp_amount_cause_rules` row x27: a principal set at step filed by a correction that carries a unit (iso4217:USD) is NOT `untagged_principal_currency_blank_in_production` | test only |
| 5 | New build test `tests/cmp_row_set_production_row_once.sql`: no production row is compared with two rows of this layer (ceiling 0). Measured 0 | 0 |

Cause ceilings: a detail with its own ceiling never counts in its cause's ceiling, so the currency `old_wrong` (0) and
`convention` (671) and the principal `owner_review` (166) cause ceilings did not need to change.

Parked, recorded only: `correction_applied_value_differs` is checked after the mechanism rules and tests only the
field's own correction id. A corrected row that a mechanism rule explains is not flagged by it. 0 rows affected today.

## 5. Measurements for consolidation (slice 5 Task 6)

Measured 2026-11-25 on the build at 282283ad (branch `warehouse-slice5`). Measure only: nothing here changes a model,
a ceiling or a correction. The owner asked for these counts as input to a later exercise: turning repeated
corrections that each name one row into reusable filer rules. Queries in `warehouse/scripts/slice5/`, run with
`warehouse/scripts/slice2/run_sql.py`. Funds: Ares 0001287750, BCRED 0001803498, Blue Owl 0001812554, Apollo
0001837532, HPS 0001838126.

Two words used throughout:

- **Pinned**: the correction names one filing (accession) and one row in it (a context id, an identifier text or a
  production row id). It can only ever fix that row.
- **Reusable**: it names no row. It is a filer-level rule (all quarters) or a dated rule (a quarter or a range of
  quarters) that selects rows by a condition, so it can fix rows in filings that do not exist yet.

### 5.1 Pinned versus reusable

**Loaded corrections** (`stg_correction`, `q_t6_pinned_summary.sql`; per field: `q_t6_pinned_reusable.sql`). All
4,411 are pinned; 0 are reusable. No store the loader reads can hold a reusable entry: each is keyed by a row.

| Fund | Store | Kind | Corrections | Fields | Filings | Pinned | Reusable |
|---|---|---|---:|---:|---:|---:|---:|
| Ares | row_corrections | value | 195 | 14 | 16 | 195 | 0 |
| Ares | row_corrections_by_context | value | 186 | 2 | 11 | 186 | 0 |
| Ares | wrapper untagged_values | value | 6 | 2 | 2 | 6 | 0 |
| Ares | wrapper rate_verification_anchors | evidence | 16 | 2 | 8 | 16 | 0 |
| Ares | agent_investigate_rules (row_add, 8 positions) | add_row | 212 | 30 | 2 | 212 | 0 |
| Ares | agent_b2_corrections (by production row id) | value | 3 | 3 | - | 3 | 0 |
| BCRED | row_corrections | value | 18 | 6 | 6 | 18 | 0 |
| BCRED | row_corrections_by_context | value | 1,132 | 14 | 12 | 1,132 | 0 |
| BCRED | wrapper untagged_values | value | 1 | 1 | 1 | 1 | 0 |
| Blue Owl | row_corrections | value | 171 | 15 | 13 | 171 | 0 |
| Blue Owl | row_corrections_by_context | value | 211 | 6 | 11 | 211 | 0 |
| Blue Owl | wrapper relabelled_contexts | relabel | 202 | 1 | 1 | 202 | 0 |
| Apollo | row_corrections | value | 852 | 17 | 14 | 852 | 0 |
| Apollo | row_corrections_by_context | value | 273 | 10 | 14 | 273 | 0 |
| Apollo | wrapper untagged_values | value | 57 | 3 | 14 | 57 | 0 |
| HPS | row_corrections | value | 177 | 8 | 11 | 177 | 0 |
| HPS | row_corrections_by_context | value | 696 | 16 | 14 | 696 | 0 |
| HPS | wrapper pik_margin_reading | exception | 3 | 1 | 3 | 3 | 0 |
| **Total** | | | **4,411** | | | **4,411** | **0** |

**Agent rules** (`stg_correction_rule` and the add_row groups, `q_t6_pinned_rules.sql`; each read by hand). Of the
14 live investigator rules (12 exclusions, 2 row_add) and the 2 B2 leaves:

| Class | Rules | Which |
|---|---:|---|
| Reusable, all quarters (a condition on the row) | 6 | BCRED 2 (cash rows; footnote figures on the issuer), Blue Owl 2 (issuer-only roll-forward rows; one named vehicle's issuer-only rows), Ares 1 (issuer-only supplemental rows), Apollo 1 (industry and instrument subtotal rows) |
| Reusable, dated (a condition, one quarter) | 2 | Blue Owl 2025-12-31 (bare-axis roll-forward leaks); B2 comparative-period filter, Ares 2025-12-31 |
| Pinned exclusion (names rows) | 5 | Ares 2025-09-30 (two row ids), Ares 2023-06-30 and 2024-03-31 (one member text each), Blue Owl 2026-03-31 (a context list, plus a range-axis condition), Apollo 2023-09-30 (one identifier and one fair value) |
| Pinned addition | 2 | Ares row_add 2025-03-31 and 2025-06-30, 4 listed positions each |
| Pinned value fix | 1 | B2 all-PIK fix, Ares, one production row id (3 value corrections) |

Same as measured 2026-11-24 (the plan's appendix and Task 6 brief): 4,196 corrections then, plus the 215 agent
corrections loaded since (212 add_row, 3 B2), all pinned; the rule classes are unchanged. Note: the 8 reusable rules
are all row removals and are not applied by this layer (decision D20); its row roles reproduce what they remove.

### 5.2 Repeats: the same fix to the same position in more than one quarter

Scope: the 3,978 value corrections (kind `value`: the two row stores, the wrapper untagged values, the B2 leaf). Each
is placed on production's holdings row it keys, as production applies it (context id: accession and context;
identifier: accession and trimmed identifier; B2: production row id). That row gives the quarter (its report date;
wrapper entries carry no date of their own) and the position. All 3,978 find a production row.

Definitions:

- **Same position**, two measures. (1) Production's `position_id` of the target row. It links quarters within one
  production build only; ids are not stable across builds (AGENTS.md). (2) The same fund and the same identifier text
  (trimmed) of the target row.
- **Same fix**: the same field and the same value. An empty value means "withdraw". A number is compared rounded
  (dollar fields to the dollar, every other number to 6 decimals; the comparison tolerances are 1 dollar and well
  below 1e-6). Text is compared trimmed. The unit is not part of the fix. Comparing the exact text instead gives the
  same counts (`q_t6_repeats_exact.sql`).
- A **position-field** is one position and one field. It is **in a repeat** when one fix value is applied to it in two
  or more quarters. **Corrections in a repeat** counts every correction inside such a group, each once.
- Counted across stores: a fix made by the context store in one quarter and by the identifier store in the next is
  one repeat. Counted inside each store instead, Apollo has 2 more position-fields and 2 fewer corrections in a repeat
  (two position-fields corrected by both stores); every other fund is the same (`q_t6_repeats_fund.sql`, `within_store`).

**Per fund, measure (1) position id** (`q_t6_repeats_fund.sql`, `across_stores`):

| Fund | Value corrections | Position-fields corrected | ...in 2+ quarters | ...same fix in 2+ quarters | Corrections in a repeat |
|---|---:|---:|---:|---:|---:|
| Ares | 390 | 284 | 74 | 67 | 165 |
| BCRED | 1,151 | 960 | 152 | 152 | 344 |
| Blue Owl | 382 | 298 | 57 | 40 | 106 |
| Apollo | 1,182 | 857 | 180 | 161 | 462 |
| HPS | 873 | 314 | 168 | 155 | 655 |
| **Total** | **3,978** | **2,713** | **631** | **575** | **1,732** |

**Per fund, measure (2) identifier text** (same query):

| Fund | Position-fields corrected | ...in 2+ quarters | ...same fix in 2+ quarters | Corrections in a repeat |
|---|---:|---:|---:|---:|
| Ares | 281 | 77 | 73 | 176 |
| BCRED | 931 | 136 | 136 | 332 |
| Blue Owl | 309 | 52 | 41 | 100 |
| Apollo | 1,006 | 130 | 124 | 294 |
| HPS | 373 | 209 | 190 | 635 |
| **Total** | **2,900** | **604** | **564** | **1,537** |

The two measures disagree both ways. Identifier text finds fewer repeats where the text changes between quarters
(Apollo: 1,006 position-fields by text against 857 by id). It finds more at HPS (209 against 168 corrected in 2+
quarters), probably where production gives one loan a new id in a later quarter. Neither reason was checked row by row.

**Per fund and store, measure (1)** (`q_t6_repeats_store.sql`; repeats counted inside each store; per field:
`q_t6_repeats.sql`):

| Fund | Store | Value corrections | Position-fields | Same fix in 2+ quarters | Corrections in a repeat |
|---|---|---:|---:|---:|---:|
| Ares | row_corrections | 195 | 164 | 17 | 44 |
| Ares | row_corrections_by_context | 186 | 111 | 50 | 121 |
| Ares | wrapper untagged_values | 6 | 6 | 0 | 0 |
| Ares | agent_b2_corrections | 3 | 3 | 0 | 0 |
| BCRED | row_corrections | 18 | 19 | 0 | 0 |
| BCRED | row_corrections_by_context | 1,132 | 940 | 152 | 344 |
| BCRED | wrapper untagged_values | 1 | 1 | 0 | 0 |
| Blue Owl | row_corrections | 171 | 132 | 17 | 53 |
| Blue Owl | row_corrections_by_context | 211 | 166 | 23 | 53 |
| Apollo | row_corrections | 852 | 635 | 114 | 307 |
| Apollo | row_corrections_by_context | 273 | 174 | 45 | 144 |
| Apollo | wrapper untagged_values | 57 | 50 | 2 | 9 |
| HPS | row_corrections | 177 | 68 | 26 | 114 |
| HPS | row_corrections_by_context | 696 | 246 | 129 | 541 |

(BCRED's 18 identifier corrections reach 19 position-fields: one identifier matches two positions.)

**By what the field is** (`q_t6_repeats_step.sql`, measure (1), across stores). The step comes from seed
`correction_field`: `deferred` is a field this layer does not hold yet (names, industry, classes, reference-rate
text); the others are fields it holds (amounts, rates, currency and FX companions).

| Fund | Corrections in a repeat, field held here | Corrections in a repeat, field not held (deferred) |
|---|---:|---:|
| Ares | 38 | 127 |
| BCRED | 36 | 308 |
| Blue Owl | 78 | 28 |
| Apollo | 163 | 299 |
| HPS | 295 | 360 |
| **Total** | **610** | **1,122** |

The largest single groups (store and field, corrections in a repeat): HPS industry 226 of 227; BCRED reference-rate
source and type 130 each (of 348); Apollo principal currency 93 (identifier store); Apollo issuer name 84; Ares issuer
name 78; HPS coupon type 75, shares 74, spread 72.

### 5.3 Against the plan's appendix (measured 2026-11-24)

The plan gave, by position id over all value corrections: Ares 67 / 165, BCRED 152 / 344, Blue Owl 40 / 106,
Apollo 159 / 447, HPS 155 / 645 (position-fields with the same fix in 2+ quarters / corrections in a repeat); 1,707 of
3,975. The only entries added since are the 3 B2 corrections (Ares; none in a repeat). Ares, BCRED and Blue Owl
agree exactly. Apollo and HPS differ by 25 corrections and 2 position-fields; all of it is two differences of
definition, each measured:

| Difference | How measured | Apollo | HPS |
|---|---|---:|---:|
| This measure (above) | `q_t6_repeats_fund.sql` | 161 / 462 | 155 / 655 |
| The appendix took the quarter from the correction's own date, so the wrapper untagged values (no date) could not repeat. Here they take the date of their row | `q_t6_repeats_storedate.sql` | 159 / 453 | 155 / 655 |
| The appendix kept one fix per position-field. Here every fix that repeats counts: Apollo has 2 position-fields with two repeating fixes (6 corrections outside the larger group), HPS 3 (10) | `q_t6_repeats_diag4.sql` | 159 / 447 | 155 / 645 |

After both, every fund equals the appendix: 1,707 corrections. Two other explanations were tested and ruled out:
the rounding of numbers (`q_t6_repeats_exact.sql`) and placing the row through this layer's key resolution instead of
production's (`q_t6_repeats_target.sql`); both give the counts above unchanged. Checks that did not explain it and are
kept for the record: `q_t6_repeats_diag.sql` (by key route and reach), `q_t6_repeats_diag2.sql` (untrimmed
identifiers), `q_t6_repeats_diag3.sql` (published-basis production rows only).

The definitions here are kept (wrapper entries dated by their row; every repeating fix counted) because both count
real repeats the appendix left out.

### 5.4 What these definitions miss

- A fix whose value changes each quarter because the underlying amount moves (a corrected principal, a rate reset)
  is not "the same fix", though the mechanism is the same. The "in 2+ quarters" column counts these; the gap between
  it and "same fix" (631 against 575 by position id) is an upper bound on them.
- A position whose id changes between quarters (matching breaks, a relabel) splits one repeat into two on measure
  (1). Measure (2) catches some of these and misses others.
- Identifier text that changes between quarters hides a repeat on measure (2).
- A correction keyed by identifier that hits several rows counts once per position (BCRED: one correction, two
  positions).
- Production's position ids are from one build (2026-11-16) and not stable across builds: the counts by id hold for
  that build only.
- The measure says nothing about whether a reusable rule could replace a repeat, or whether a repeated fix is right.
  That is the later exercise. A repeat may also be a sign that the reading itself is wrong for that filer (for
  example, 226 of HPS's 227 industry corrections repeat), which a filer rule would fix more cleanly than a correction.

Agreement with production is not correctness: these are production's own corrections, counted, not checked.
