# Marts: column-by-column, with sources (draft 1, 2026-11-18)

Scope: the five v0.5 funds. 71,477 holdings rows, 2022-09-30 to 2026-06-30, of which 10,740 are JV-schedule rows
(BCRED, Blue Owl, HPS). "Source today" is what step 1 reads. "Source later" is the target table that replaces it
as the layers behind the marts are rebuilt. Fill rates are for the five funds (`probe_mart_sources.out.txt`).

Holdings = `private_markets_holdings.parquet`.

## fact_observation

Grain: one position, one fund, one report date. Key: `row_id`.

| Column | Source today | Fill | Source later | Note |
|---|---|---|---|---|
| `row_id` | holdings.`row_id` | 100% | `observation` | Hash of accession + context. Unique. |
| `cik` | holdings.`cik` | 100% | `observation` | To `dim_fund`. |
| `report_date` | holdings.`report_date` | 100% | `observation` | To `dim_date`. |
| `accession_number` | holdings.`accession_number` | 100% | `observation` | To `dim_filing`. |
| `position_id` | holdings.`position_id` | 100% | `position_assignment` | To `dim_position`. Not stable across rebuilds today. |
| `entity_id` | holdings.`entity_id` | 100% | `position` | To `dim_entity`. Carried on the fact for convenience. |
| `accounting_scope_id` | holdings.`accounting_scope_id` | 100% | `schedule` | Fund's own schedule or a named JV's. |
| `is_published` | derived: `accounting_record_class` is not `underlying_schedule` | 100% | `schedule` | The published basis (owner ruling 2026-09-30). |
| `is_cash` | derived: `asset_category` is `CASH` | 100% | same | A cash or cash-equivalent line. Published and counted; tagged so totals can be taken with or without it. Apollo only (18 rows). |
| `fair_value` | holdings.`fair_value` | 100% | `observation` | USD. |
| `cost_reported` | holdings.`cost_reported` | 97.1% | `observation` | Cost as filed. |
| `cost` | holdings.`cost` | 97.1% | `observation` | Cost including the approved proxy where none is filed. |
| `cost_is_proxy` | derived from `cost_donor_audit`.`method` | not measured | `observation_field` | |
| `principal_amount` | holdings.`principal_amount` | 84.0% | `observation` | In its original currency. |
| `principal_amount_currency` | holdings.`principal_amount_currency` | 83.3% | `observation` | |
| `principal_amount_usd` | holdings.`principal_amount_usd` | 84.0% | `observation` | |
| `principal_fx_status` | holdings.`principal_fx_status` | 84.0% | `observation_field` | `source_usd`, `reference_fx`, `missing_reference_fx`. |
| `shares_held` | holdings.`shares_held` | 11.2% | `observation` | |
| `pct_of_net_assets_reported` | holdings.`pct_of_net_assets` | 42.9% | `observation` | As filed. |
| `pct_of_net_assets_calculated` | holdings.`pct_of_net_assets_calculated` | 95.9% | derived in the mart from `fund_period` | Fair value over fund NAV. |
| `interest_rate` | holdings.`interest_rate` | 60.8% | `observation` | See `interest_rate_kind`. |
| `interest_rate_kind` | holdings.`interest_rate_kind` | 100% | `observation_field` | `all_in`, `cash`, `unresolved`. |
| `interest_rate_reported` | holdings.`interest_rate_reported` | 60.3% | `observation` | The filed figure before any reading. |
| `interest_rate_cash` | holdings.`interest_rate_cash` | 4.1% | `observation` | |
| `pik_rate` | holdings.`pik_rate` | 7.9% | `observation` | |
| `basis_spread` | holdings.`basis_spread` | 79.6% | `observation` | |
| `basis_spread_kind` | holdings.`basis_spread_kind` | 100% | `observation_field` | `unresolved` on every row today. |
| `reference_rate_type` | holdings.`reference_rate_type` | 79.1% | `observation` | |
| `reference_rate_source` | holdings.`reference_rate_source` | 79.0% | `observation_field` | Kept on the fact because inferred values share the column with read ones. |
| `coupon_type` | holdings.`coupon_type` | 82.2% | `observation` | `Fixed`, `Floating`. |
| `maturity_date` | holdings.`maturity_date` | 82.7% | `observation` | |
| `maturity_precision` | holdings.`maturity_precision` | 100% | `observation_field` | `day`, `month`, `unknown`. |
| `nonaccrual_status` | holdings.`nonaccrual_status` | 100% | `observation` | `nonaccrual`, `unknown`. |
| `pik_current_status` | `position_pik_status`.`pik_current_status` | not measured | `observation` | Joined on fund, report date and position, not on that table's row number. A test checks that the matched row has the same accession and fair value. |
| `pik_terms_flag` | `position_pik_status`.`pik_terms_flag` | not measured | `observation` | A proxy for disclosed PIK terms, not proof of current PIK income. |
| `issuer_name_as_filed` | holdings.`issuer_name` | 100% | `observation` | |
| `instrument_description` | holdings.`instrument_description` | 55.9% | `observation` | |
| `industry_as_filed` | holdings.`extracted_industry` | 93.7% | `observation` | The fund's own label. |
| `source_identifier` | holdings.`bdc_investment_identifier` | 100% | `source_row` | The position's name string in the filing. |
| `asset_category_as_read` | holdings.`asset_category` | 100% | `observation` | Class as read this quarter. In step 1 this is the only place class is held (owner decision 2026-11-18). |
| `lien_position_as_read` | holdings.`lien_position` | 81.3% | `observation` | |
| `instrument_type_as_read` | holdings.`instrument_type` | 17.6% | `observation` | Low fill today. |
| `index_classification` | holdings.`index_classification` | 100% | derived from class | |
| `exposure_type` | holdings.`exposure_type` | 100% | derived from class | Added 2026-11-18: used by the fund exposure figures. `DIRECT`, `FUND`, `LIQUID`. |
| `asset_class` | holdings.`asset_class` | 100% | derived from class | Added 2026-11-18: used by the fund exposure figures. |
| `gics_sector_as_read` | holdings.`gics_sector` | 96.3% | `observation`, then `entity` once sector is a decision record | Kept on the fact in step 1 (owner decision 2026-11-18), so the sector figures match the website exactly. |
| `gics_sub_industry_as_read` | holdings.`gics_sub_industry` | 96.3% | same | |
| `nonaccrual_footnote` | holdings.`nonaccrual_footnote` | 100% | `observation` | Added 2026-11-18: the credit-risk figures read this flag, not `nonaccrual_status`. |
| `nonaccrual_dimension` | holdings.`nonaccrual_dimension` | 100% | `observation` | Added 2026-11-18: same. |
| `has_correction` | derived: `corrected_fields` is not empty | 2.9% true | `observation_field` | |
| `src_context_id` | holdings.`src_context_id` | 100% | `source_row` | Link back to the filing. |

Left out on purpose: the 14 `nport_*` columns, `cusip`, `isin`, `lei`, `ticker`, `fair_value_level` (all empty for
BDCs), the dead columns, `src_facts` (a JSON column), `entity_name` and `canonical_name` (they move to the
dimensions).

Step 1 scope (owner decision 2026-11-18): position-level figures only. The website's position-based figures
(headline fair value, sector and instrument donuts, spreads, credit risk, PIK, portfolio characteristics, fund
exposure and top holdings) are covered by this table. Not covered, and left for later steps: fund-level figures
from `fund_financials.csv` (about 30 columns), the concentration and contribution charts from
`position_returns.csv`, the industry breakdown from the fund-level sector tables, the data quality page, and
derivatives. The website keeps reading the existing outputs. Basis: `probe_frontend_columns.out.txt`, a
mechanical pass that is a ceiling on the columns used.

## fact_fund_period (AGREED by owner 2026-11-18, narrowed)

Grain: one fund, one report date. One row per fund and report date that has positions, or has a financials row at a
report date present in the holdings: 80 rows for the five funds today (74 with positions, 6 without). Purpose:
reconcile the published positions against the fund's filed total, supply the NAV denominator, and show
fund-quarters that have financials but no positions.

| Column | Source today | Fill | Source later | Note |
|---|---|---|---|---|
| `cik`, `report_date` | holdings, and `fund_financials.csv` for fund-quarters without positions | 80 of 80 fund-dates | `fund_period` | |
| `accession_number` | holdings (one accession per fund-date, verified) | 74 of 80 | `fund_period` | The filing selected. Empty for a fund-quarter without positions. |
| `has_positions` | derived: the fund-quarter has holdings rows | 100% (74 true, 6 false) | same | False for a fund-quarter that has financials and no positions. |
| `net_assets` | `fund_financials`.`net_assets` | 80 of 80 | `fund_period` | From companyfacts. |
| `total_assets` | `fund_financials`.`total_assets` | 77 of 80 | `fund_period` | From companyfacts. Empty for three fund-quarters without positions (2022-09-30). |
| `investments_at_fair_value_filed` | `fund_financials`.`investments_at_fair_value` | 77 of 80 | `schedule`.filed total, from the selected filing's own tagged facts | From companyfacts. Covers the fund's own schedule only; JV schedules have no filed total. Empty where no filed total exists (three 2022-09-30 fund-quarters). |
| `published_fair_value` | derived: sum of `fact_observation`.`fair_value` where `is_published` | 100% | same | |
| `cash_fair_value` | derived: sum of published `fair_value` where `is_cash` | 100% | same | |
| `published_fair_value_ex_cash` | derived | 100% | same | |
| `cash_equivalents_filed` | `fund_financials`.`cash_equivalents_at_fair_value` | as filed | same | |
| `difference_to_filed` | derived | 100% | same | Published, cash rows included, minus the filed investments line. |
| `difference_to_filed_ex_cash` | derived | 100% | same | The same without the cash rows. |
| `filed_total_excludes_cash` | derived | 100% | same | True when the total with cash misses the filed line, the total without it ties, and the cash rows equal the filed cash equivalents within 0.5 pct of the investments line (evidence half of the owner ruling of 2026-11-04, check A04). Wrapper declarations are not read. |
| `difference_to_filed_on_basis` | derived | 100% | same | The reconciliation result: ex cash where `filed_total_excludes_cash`, else with cash. |

The three companyfacts columns have no known defect for the five funds. Fill was verified; correctness was not,
beyond one direct check (Ares 2026-03-31: companyfacts equals the total row printed in the filing, 29,499.3M).
Companyfacts is independent of our parser but not of the filer's tagging, and it is not tied to the filing
selected. It is a temporary source: once the parse-once layer exists, the totals come from the selected filing
and companyfacts becomes a cross-check.

Left out of step 1 on purpose, until their defects are fixed (owner decision 2026-11-18):

| Column | Source | Defect |
|---|---|---|
| `nav_per_share` | `fund_financials.csv`; which path fills it was not traced | HPS extracted as 1000; Blue Owl missing (60 of 74 filled). |
| `total_investment_income`, `net_investment_income`, `total_expenses` | `bdc_fund_income.csv`, from the filing's XML | In a 10-K quarter these are the annual figure divided by four. |

## dim_fund

| Column | Source today | Note |
|---|---|---|
| `cik` | `bdc_universe.csv` | Key. |
| `fund_name` | `fund_financials.csv`.`entity_name`, at the fund's latest quarter with total assets, with any "(CIK ...)" suffix stripped | The same source and rule as the website (`pipeline/export/fund_exports.py`, `_export_fund_list` and `_display_fund_name`). One name per fund for all five. `fund_financials.py` fills it from the financial data's own name and falls back to the universe file only when blank; where the financial data's name originates was not traced. The universe file's own name is not used: it is decorated ("ARES CAPITAL CORP (ARCC) (CIK 0001287750)") and stale ("Owl Rock Core Income Corp."). |
| `adviser_id` | seed file made from `CIK_TO_MANAGER_BRAND` in `pipeline/config.py` | To `dim_adviser`. The website uses `fund_identity.csv`.`adviser_name` first and this mapping second; `fund_identity.csv` contains none of the five, and `adviser_name` is blank in the universe file for all five. |
| `vehicle_type` | `bdc_universe`.`vehicle_type` | `bdc`. |
| `status` | `bdc_universe`.`status` | |
| `bdc_election_date` | `bdc_universe`.`election_date` | |
| `first_filing_date` | `bdc_universe`.`first_filing_date` | |
| `cohort_status` | cohort manifest JSON | Active, deferred or held back. |
| `is_v05` | `quarter_acceptance_thresholds.json` (`findings_scope.ciks`) | |

## dim_adviser

| Column | Source today | Note |
|---|---|---|
| `adviser_id` | seed file made from `CIK_TO_MANAGER_BRAND` in `pipeline/config.py` | Derived from the brand. Five rows for the v0.5 funds: Blackstone, Blue Owl, Ares, HPS, Apollo. |
| `manager_brand` | same seed file | The mapping holds a brand ("Blackstone"), not the registered adviser entity, so the column is named for what it is. About 140 funds are mapped in total. |

The mapping is a Python dictionary today. dbt reads tables, so it becomes a seed: a small CSV kept in the dbt
project. Until the website export is pointed at the same file, the mapping exists in two places and can drift.

## dim_entity

| Column | Source today | Note |
|---|---|---|
| `entity_id` | holdings.`entity_id` | Key. 2,303 borrowers at 2026-03-31 in the five funds. |
| `canonical_name` | `entity_lookup`.`canonical_name` | One per entity, verified. |
| `alias_count` | `entity_lookup` | Number of name variants. |
| `first_seen_date`, `last_seen_date` | derived from holdings | Within the five funds only. |

Sector is not on this table in step 1 (owner decision 2026-11-18: no temporary rule). It stays on the fact as
read, and a test counts the borrowers that carry more than one. It moves here when sector becomes a decision
record. See "Why keys carry several values" below.

## dim_position

| Column | Source today | Note |
|---|---|---|
| `position_id` | holdings.`position_id` | Key. |
| `cik` | holdings | A position never spans funds (verified). |
| `accounting_scope_id` | holdings | Never spans scopes (verified). |
| `entity_id_latest` | holdings, latest observation | 210 of 15,154 positions in the five funds span two borrower ids, so the column is named for what it is. The per-date borrower is on the fact. |
| `anchor_row_id` | derived: `row_id` of the earliest observation | The stable anchor agreed for class decisions. |
| `first_report_date`, `last_report_date`, `observation_count` | derived | |
| `issuer_name_latest`, `instrument_description_latest` | holdings, latest observation | For display. |

Class (asset category, lien, instrument type) is not on this table in step 1 (owner decision 2026-11-18: no
temporary rule). It stays on the fact as read, and tests count the positions whose class differs between
observations. It moves here when class becomes a decision record.

## dim_filing

| Column | Source today | Note |
|---|---|---|
| `accession_number` | holdings | Key. 74 filings for the five funds. |
| `cik` | holdings | |
| `form_type` | holdings.`bdc_form_type` | |
| `filing_date` | holdings.`filing_date` | One per accession, verified. |
| `report_date` | holdings | The period the filing reports. |
| `is_amendment` | derived from `form_type` | |
| `primary_document` | `bdc_filings_index.csv`, deduplicated | The index has 104 rows for these 74 accessions. |

## dim_date

| Column | Source today | Note |
|---|---|---|
| `report_date` | derived: distinct report dates | Key. 16 quarter-ends. |
| `year`, `quarter`, `quarter_label` | derived | |

## Tests on day one, and what to expect

| Test | Expectation |
|---|---|
| `fact_observation.row_id` unique | Pass. |
| Fund + date + scope + position unique | Pass. |
| Every key resolves to its dimension | Pass, once the adviser seed is created from `CIK_TO_MANAGER_BRAND`. |
| One sector per borrower | Fail: 132 of 2,303 at 2026-03-31 (30.5bn of 205.1bn fair value); 430 of 3,567 over all dates. |
| One asset category per position | Fail: 63 of 15,154. |
| One lien per position | Fail: 116 with two or more values. A further 1,247 loan positions are blank in some quarters and filled in others. |
| One instrument type per position | Fail: 6. |
| One borrower per position | Fail: 210. |
| Published fair value equals the filed total | Warn: 11 fund-quarters with positions, all Apollo (cash rows); ceiling 11. |
| Fund-quarter with financials but no positions | Warn: 6 (2022-09-30 and 2022-12-31 for Blue Owl, Apollo, HPS); ceiling 6. |
| Ceilings | Every baseline test (one sector, asset category, lien, instrument type, borrower, form type, published equals filed, fund-quarter without positions) warns while its count is above zero and fails the build above its ceiling, set in `baseline_max` in `dbt_project.yml`. A count may fall; raising a ceiling is a deliberate edit. |
| Integrity tests | Pass: one accession per fund-date; a position has one fund, one scope and one row per date; one canonical name per entity and one primary document per filing in the sources; PIK status file aligned with holdings (accession and fair value); every fund in scope has holdings at the latest date; accession present on fund-quarters with positions; `cost_is_proxy` and `pik_terms_flag` not null. |

## Why keys carry several values (investigated 2026-11-18, five funds)

Evidence: `probe_multi_value.out.txt`.

### Sector per borrower

| Finding | Figure |
|---|---|
| Sector is fixed by fund + issuer name + the fund's industry label | 7,014 of 7,016 such groups give one sector |
| A fund's industry label maps to one sector | 276 of 308 fund labels; 25 map to several, 7 to none |
| Conflicted borrowers where the funds disagree with each other | 73 of 132 |
| Conflicted borrowers where one fund's own rows disagree | 59 of 132 |
| Same fund and borrower, sector changes between quarters | 341 of 4,536 pairs |
| Borrowers with no sector at the latest date | 61: Ares 47 (label present but unmapped), Blue Owl 30 (no label, about zero fair value) |

Cause: sector is derived mainly from each fund's own industry label, and funds label the same borrower
differently (Auctane: "Software" at Blackstone, "Commercial Services & Supplies" at Apollo, "Broadline Retail" at
HPS). It is not a false merge of different companies: the name variants are the same company. Inside one fund the
examples show rows with no industry label (often unfunded lines at zero fair value) given a sector by another
route that contradicts the labelled rows (AmeriLife at Blue Owl: "Insurance" gives Financials, the unlabelled
rows give Health Care). How many of the 59 are of that kind was not counted.

Consequence: this is a modelling gap, not 132 separate errors. One sector per borrower needs a rule or a decision
that sits above the funds' labels. The unlabelled-row case is a defect to fix where the sector is produced.

### Class per position

| Attribute | Positions affected | What the changes are |
|---|---|---|
| Asset category | 63 (56 switch once, 6 switch and return) | Common equity to or from loan (25 changes), common to or from preferred (21), common to or from fund interest (11) |
| Lien | 116 with two or more values | First to or from second lien (102 changes) |
| Lien, blank in some quarters | 1,247 | Blank then First Lien (1,190 changes) |
| Instrument type | 6 | Revolver to delayed draw (5); otherwise blank to or from a value |
| Borrower | 210 | Every change coincides with a change in the issuer name as filed |

Causes seen in the examples, not apportioned:
- The same text classified differently in different quarters (Ares, Ivy Hill "Member interest": other, then
  common equity, then other; 1.9bn).
- A row matched to a different instrument of the same issuer (a loan followed by "Limited partnership interest"
  or "Series B preferred shares").
- For borrower: renames and name variants that entity resolution did not merge (BradyIFS to BradyPLUS;
  "Aerosmith Bidco Limited" to "Aerosmith Bidco 1 Limited"). A few link different legal entities ("VCI Asset
  Holdings 1 LLC" to "VCI Asset Holdings 2 LLC").

Consequences:
- Asset category, lien and instrument type conflicts are few (185 positions) and reviewable one by one.
- Holding the class on the position would fill the 1,247 blank liens from the quarters that have a value.
- The 210 borrower changes are candidates for entity merges, with position continuity as the evidence.
