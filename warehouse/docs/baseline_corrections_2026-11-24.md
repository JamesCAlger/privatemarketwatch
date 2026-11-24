# Baseline: corrections (slice 5), 2026-11-24

Sections 2 onward are written by Tasks 5 and 6. Nothing in section 1 applies a correction; it says what the stores
hold, what the loader loads and where production applies each.

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
