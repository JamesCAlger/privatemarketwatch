# Rates baseline, 2026-11-23 (slice 4 of the intermediate layer)

This layer's rate fields compared with production's. Spec: `intermediate_spine.md` section 8 (D1).
Model: `cmp_rate`. Production: `stg_holdings` (the holdings file under `data/output`, the same file
the amounts baseline read). Plan: `2026-11-23-slice4-rates-plan.md`, Task 4.

**Agreement is not correctness.** When the two sides agree, they agree. It does not show either is
right. This comparison cannot see:

- a rate both pipelines read wrongly in the same way (it counts as `equal`);
- a rate missing on both sides (it counts as `both_empty`; a missing rate is not evidence that the
  position has none);
- a change in what a field means, or offsetting errors.

Build line: `PASS=642 WARN=95 ERROR=0 TOTAL=737` (was 563 / 65 / 628). Python tests 144. CI fixture
3 / 314 / 2 / 33. A passing build does not show the data is correct.

## How the sides are joined

- Rows: the position rows both sides have (`cmp_row_set`, side `both`), both bases. The 2026-09-30
  quarters in `cmp_excluded_quarter` stay out. Published basis: 60,675 rows. Unpublished: 10,740.
- Key: accession and context id. One row per accession, context and field.
- Six fields:

| This layer | Production column | Equal when |
|---|---|---|
| interest_rate (all-in) | interest_rate | differ by no more than 1e-9 percentage points |
| interest_rate_cash (cash leg) | interest_rate_cash | the same |
| pik_rate | pik_rate | the same |
| spread | basis_spread | the same |
| maturity_date | maturity_date | same date |
| rate_kind | interest_rate_kind | same text |

- Tolerance (var `cmp_rate_tolerance`, 1e-9). Both sides multiply one tagged fraction by 100. On
  agreeing rows the largest difference is float rounding, 3.6e-15. The smallest real difference is
  0.12 (`scripts/slice4/q_t4_tolerance.sql`). Anything above 1e-9 is a difference.
- Outcomes: `equal`, `differs`, `new_empty` (production has a value, this layer none),
  `production_empty`, `both_empty`.

### Production's other rate columns

| Column | What it holds | Treated as |
|---|---|---|
| interest_rate_reported | The filed rate after production's size scaling, before the fund's reading (`financial_conventions.py` `prepare`). Equals interest_rate on 43,071 all-in rows; empty on 406 all-in rows whose rate was set without a filed rate (PIK-only coupons among them); differs on the 3 cash rows (rate = reported + PIK); set with no rate on 7 unresolved rows | Second measure. Kept beside the rate as `value_production_reported`; not compared |
| basis_spread_kind | `unresolved` on all 71,477 rows of the five funds | Out of scope: carries nothing |
| maturity_precision | `unknown` on 52,098 dated rows, `day` on 7,035, `month` on 2 | Out of scope as a pair: this layer reads full ISO dates only. Its date is compared |

Reference rate type and source are text fields: out of scope (second spec).

## Headline (published basis, all compared quarters)

| Field | Equal | Differs | New empty | Production empty | Both empty |
|---|---:|---:|---:|---:|---:|
| interest_rate | 33,479 | 10 | 978 | 850 | 25,358 |
| interest_rate_cash | 2,450 | 72 | 234 | 6 | 57,913 |
| pik_rate | 5,215 | 90 | 126 | 13 | 55,231 |
| spread | 45,614 | 5 | 962 | 426 | 13,668 |
| maturity_date | 7,023 | 0 | 44,006 | 0 | 9,646 |
| rate_kind | 58,844 | 1,831 | 0 | 0 | 0 |

Every open row (differs, new empty, production empty) has a cause. `not_yet_explained` is 0 on every
field and both bases.

Open rows by cause (published):

| Field | needs_correction | needs_store_not_loaded | owner_review | new_wrong | not_yet_explained |
|---|---:|---:|---:|---:|---:|
| interest_rate | 52 | 1,114 | 669 | 3 | 0 |
| interest_rate_cash | 132 | 177 | 3 | 0 | 0 |
| pik_rate | 158 | 55 | 16 | 0 | 0 |
| spread | 123 | 1,202 | 68 | 0 | 0 |
| maturity_date | 9 | 43,997 | 0 | 0 | 0 |
| rate_kind | 44 | 1,115 | 669 | 3 | 0 |

Unpublished basis: interest_rate 8 needs_store_not_loaded and 1 owner_review; cash the same; PIK 1
owner_review; spread 142 needs_correction and 23 needs_store_not_loaded; maturity 2 needs_correction
and 8,082 needs_store_not_loaded; kind 8 and 1. `old_wrong`, `convention` and `production_stale`: 0
everywhere.

## Per fund and field (published)

| Fund | Field | Equal | Differs | New empty | Prod. empty | Both empty |
|---|---|---:|---:|---:|---:|---:|
| Ares | interest_rate | 12,376 | 4 | 701 | 839 | 5,847 |
| Ares | interest_rate_cash | 1,145 | 0 | 65 | 0 | 18,557 |
| Ares | pik_rate | 2,554 | 14 | 57 | 1 | 17,141 |
| Ares | spread | 12,745 | 3 | 14 | 1 | 7,004 |
| Ares | maturity_date | 0 | 0 | 14,556 | 0 | 5,211 |
| Ares | rate_kind | 18,226 | 1,541 | 0 | 0 | 0 |
| BCRED | interest_rate | 14,320 | 0 | 72 | 0 | 1,107 |
| BCRED | interest_rate_cash | 703 | 0 | 77 | 0 | 14,719 |
| BCRED | pik_rate | 921 | 0 | 5 | 0 | 14,573 |
| BCRED | spread | 13,905 | 0 | 2 | 309 | 1,283 |
| BCRED | maturity_date | 0 | 0 | 14,406 | 0 | 1,093 |
| BCRED | rate_kind | 15,427 | 72 | 0 | 0 | 0 |
| Blue Owl | interest_rate | 0 | 0 | 106 | 0 | 9,613 |
| Blue Owl | interest_rate_cash | 0 | 0 | 0 | 0 | 9,719 |
| Blue Owl | pik_rate | 712 | 6 | 8 | 0 | 8,993 |
| Blue Owl | spread | 6,328 | 0 | 491 | 36 | 2,864 |
| Blue Owl | maturity_date | 0 | 0 | 6,908 | 0 | 2,811 |
| Blue Owl | rate_kind | 9,613 | 106 | 0 | 0 | 0 |
| Apollo | interest_rate | 312 | 6 | 28 | 11 | 6,891 |
| Apollo | interest_rate_cash | 6 | 2 | 57 | 3 | 7,180 |
| Apollo | pik_rate | 260 | 0 | 11 | 8 | 6,969 |
| Apollo | spread | 6,402 | 2 | 275 | 10 | 559 |
| Apollo | maturity_date | 7,023 | 0 | 2 | 0 | 223 |
| Apollo | rate_kind | 7,207 | 41 | 0 | 0 | 0 |
| HPS | interest_rate | 6,471 | 0 | 71 | 0 | 1,900 |
| HPS | interest_rate_cash | 596 | 70 | 35 | 3 | 7,738 |
| HPS | pik_rate | 768 | 70 | 45 | 4 | 7,555 |
| HPS | spread | 6,234 | 0 | 180 | 70 | 1,958 |
| HPS | maturity_date | 0 | 0 | 8,134 | 0 | 308 |
| HPS | rate_kind | 8,371 | 71 | 0 | 0 | 0 |

Read the both-empty column with care: Blue Owl files no interest-rate tag, so neither side has its
all-in rate on 9,613 published rows. Agreement there is agreement on nothing.

Causes per fund and field: `scripts/slice4/q_t4_fund_outcomes.sql`.

## Causes

Each cause is set by a rule on row features (production's own source, transform and fill labels,
its corrected fields, this layer's reason). No list of ids. The rule order is in the header of
`models/intermediate/cmp_rate.sql`. "Opened" means the printed schedule row of the position was read
from the filed layer (`scripts/slice4/q_t4_open_rows.sql`, up to 4 rows per field and cause detail,
148 rows in all). "Check" is an independent test of the mechanism on every row of the group
(`scripts/slice4/q_t4_mechanism_checks.sql`).

### needs_correction: a correction production applied (published 518 rows across fields)

- Rule: a loaded value correction (`stg_correction`) sets a field that sets this one, and production's
  `corrected_fields` names such a field. Covers: the rate, cash leg and kind are set by a correction
  of the rate, the kind or the PIK rate; the PIK rate by a PIK correction; the spread by a spread
  correction; the maturity by a maturity correction.
- Counts: rate 52, cash 132, PIK 158, spread 123, maturity 9, kind 44 (unpublished: spread 142,
  maturity 2).
- Check: a correction on the field itself carries production's value on 48 of 52 rates, 158 of 158
  PIK rates, 123 of 123 spreads, 9 of 9 maturities, 27 of 44 kinds. The rest (and all 132 cash legs,
  which no correction names) are set through a covering field.
- Opened: 24. Example: Apollo 2026-03-31, printed "5.38% Cash plus 5.38% PIK": this layer stores the
  tag 5.38 as the all-in rate; production's correction gives 10.76. Apollo 2025-12-31: the tag is
  0.001036 (this layer 0.1036); printed 10.36%; production's correction gives 10.36.
- These wait for slice 5 (corrections).

### needs_store_not_loaded: production used an input this layer does not read yet

| Detail | Missing input | Published rows (rate / cash / PIK / spread / maturity / kind) | Opened |
|---|---|---|---:|
| printed_maturity_not_read | Maturity printed on the schedule row (production's source `ixbrl_field_status`) | 0 / 0 / 0 / 0 / 43,996 / 0 | 4 |
| printed_total_margin_not_read | The printed total margin (`printed_margin_cash_plus_pik`; this layer's reason `text_not_read`) | 0 / 0 / 0 / 479 / 0 / 0 | 4 |
| pik_only_reading_needs_printed_text | Printed reference rate and coupon type (the two PIK-only readings tie; reason `rule_conflict`) | 132 / 0 / 0 / 287 / 0 / 132 | 12 |
| printed_reference_rate_column_not_read | The printed reference-rate column ("N/A" or blank): production moves the spread tag to the rate or drops it | 112 / 76 / 0 / 413 / 0 / 112 | 16 |
| loan_class_not_read | Production's loan class (`asset_category`, from text). Production applies the coupon reading to loans only | 838 / 0 / 0 / 0 / 0 / 838 | 8 |
| identifier_text_not_read | Rates and dates production read from the identifier text (source `identifier_text`) | 23 / 55 / 9 / 19 / 1 / 23 | 21 |
| whole_coupon_pik_not_read | Wrapper procedure `pik_margin_reading whole_coupon` (production label `pik_rate:whole_coupon_printed`) | 3 / 44 / 44 / 0 / 0 / 3 | 14 |
| rate_only_context_not_adopted | Wrapper procedure `rate_only_contexts adopt_adjacent` (production names the moved fields in `src_filled_fields`) | 6 / 1 / 2 / 4 / 0 / 6 | 15 |
| production_corrected_no_loaded_store | A correction production applied that is not in the loaded store | 0 / 1 / 0 / 0 / 0 / 1 | 2 |

Evidence per detail:

- **printed_maturity_not_read.** Only Apollo tags maturity. Every other fund's maturity in
  production comes from the printed row. Check: production has a date on all 43,996 rows. Opened
  rows print the date (for example "03/2029" for Ares, "9/30/2030" for HPS).
- **printed_total_margin_not_read.** Production summed spread and PIK on 268 rows (label
  `basis_spread:cash_plus_pik_margin`) and kept the filed spread on 210. Check: 478 of 479 match one
  of those two; the last one is the sum after production's size rule (filed spread 5.55, a percent).
  Opened: Blue Owl "S+ | 3.50% | 4.25%" (production 7.75), Apollo "SONIA+350 Cash plus 2.00% PIK"
  (production 5.50).
- **pik_only_reading_needs_printed_text.** Blue Owl and HPS declare both PIK-only readings. Production
  read 132 rows as the coupon (label `interest_rate:pik_only`, rate = PIK) and 287 as the margin
  (label `basis_spread:pik_margin`, spread = PIK). Check: 132 and 287 of 132 and 287. Opened: "12.00%
  PIK" with no reference rate (coupon), "SR + | 10.50% PIK" (margin).
- **printed_reference_rate_column_not_read.** Production labels `interest_rate:from_spread_tag` and
  `basis_spread:fixed_coupon`. Check: on every rate row production's rate equals the filed spread
  tag times 100; on every spread row production's spread is empty. Opened: BCRED "AI Altius | 9.75% |
  9.75% PIK", Blue Owl "Dealer Tire | Unsecured notes | 8.00%" (fixed coupons tagged as spreads).
- **loan_class_not_read.** All 838 are Ares rows production classes as preferred or common equity or
  a fund (658 / 171 / 9). Production's rate is empty and its kind `unresolved` on all 838. Opened:
  "Series A preferred shares | 10.50% PIK", "Class A units | 8.00% PIK". This layer stores the
  preferred dividend as an all-in rate under the coupon ruling of Task 3.
- **identifier_text_not_read.** All Apollo. Opened: "Unsecured Debt - Corporate Bond | 4.75%" with
  no rate tag; "11.81% PIK" where the PIK rate comes from the text, so production's cash leg is 0.
- **whole_coupon_pik_not_read.** HPS. Production changed 49 rows; 44 land here, 5 are taken by a
  correction first. Check: production's PIK rate equals its all-in rate and its cash leg is 0 on
  all. Opened: "SF + | 6.25% PIK | 10.07 %": this layer PIK 6.25, production PIK 10.07; "SF + | 5.50%
  PIK | 9.34 %": this layer cash 3.84, production cash 0. The Task 3 approximation of the printed grammar found about 171 candidate rows;
  production's narrower grammar changed 49.
- **rate_only_context_not_adopted.** Ares. Production named rate fields in `src_filled_fields` on 6
  rows; the Task 3 approximation finds 7 pairs (re-run today: 2023-12-31 1, 2025-03-31 1, 2025-06-30
  3, 2025-09-30 2). Opened: "12.40% (2.00% PIK) | SOFR (Q) | 7.00%" printed on the value row, the
  tags on the neighbouring context.

### owner_review: production decides by the size of the number

- **scale_decided_by_size_in_production** (published: rate 668, cash 2, PIK 16, spread 68, kind 668;
  unpublished 1 each on rate, cash, PIK, kind). This layer's reason is `scale_not_decided`: a value
  above 1 in a ratio unit. Production keeps a value between 0.5 and 50 as a percent and divides one of
  50 or more by 100 (`pipeline/staging_bdc.py` `_prepare_bdc`). Check: production's value is that
  size rule applied to the filed value on every rate, PIK and spread row. Opened: 19, for example Ares
  "9.58%" tagged 9.58 in `utr:Rate`, Apollo "S+450" tagged 4.5. Production's value matches the print
  on every row opened. That makes production right on those rows, by a rule this layer has not been
  allowed to adopt. Owner decision 4 of the Task 3 owner-review file.
- **two_values_filed_production_keeps_first** (rate 1, cash 1, kind 1). Ares 2025-06-30 c-32: the
  rate is filed twice, 0.1005 and 0.098. This layer withholds it (`values_differ`). Production keeps
  the first fact in the instance: 9.80, which is what the page prints. Opened: 3 (one position).

### new_wrong: a defect in this layer (not patched; controller decides)

- **coupon_read_on_printed_floating_margin** (rate 3, kind 3). Apollo, two loans:

| Quarter | Context | Printed rate | This layer | Production |
|---|---|---|---|---|
| 2023-06-30 | C_8a5fa6bf-... | S+450 PIK | all-in 4.50, kind all_in | rate empty, spread 4.50 (text) |
| 2023-09-30 | C_3a1d2f29-... | S+450 PIK | all-in 4.50, kind all_in | rate empty, spread 4.50 (text) |
| 2023-09-30 | C_94c123f3-... | S+610 Cash (includes 5.97% PIK) | all-in 5.97, kind all_in | rate empty, spread 6.10 (text) |

  The PIK tag is a margin over SOFR, not the coupon. The coupon reading (`pik_only_is_coupon`, applied
  to every PIK-only row by Task 3 ruling 2) stores it as the all-in rate. The true all-in rate is about
  SOFR plus the margin. Production avoids it because it read a spread from the text.
- Proposed fix (for the controller): the coupon reading needs a test that the row prints no reference
  rate, which is printed text (the text spec). Until then the options are to leave these rows
  unresolved when the identifier or printed row names a benchmark, or to accept the 3 rows as a known
  defect under this ceiling. Not patched here. Opened: 6 (the 3 positions, rate and kind).

## Unresolved in this layer (Tasks 2 and 3), and where they land

All rows, all quarters (`int_field_normalised`; `scripts/slice4/q_t4_by_design.sql`):

| This layer's reason | Field | Not compared | Both empty | Cause given (published, unless noted) |
|---|---|---:|---:|---|
| rule_conflict (628 Blue Owl and HPS positions) | interest_rate | 33 | 462 | 132 pik_only_reading_needs_printed_text; 1 needs_correction |
| rule_conflict | spread | 33 | 307 | 287 pik_only_reading_needs_printed_text; 1 needs_correction |
| text_not_read (540) | spread | 46 | 8 | 479 printed_total_margin_not_read; 7 needs_correction |
| scale_not_decided (679 / 20 / 68) | interest_rate | 0 | 6 | 668 owner_review; 3 whole_coupon_pik_not_read; 1 needs_correction; unpublished 1 owner_review |
| scale_not_decided | pik_rate | 0 | 0 | 16 owner_review; 3 whole_coupon_pik_not_read; unpublished 1 owner_review |
| scale_not_decided | spread | 0 | 0 | 68 owner_review |
| pik_above_rate (15) | interest_rate | 0 | 0 | 15 needs_correction (production's rate comes from a correction) |
| values_differ (Task 2, 6 Ares rows) | interest_rate / spread | 0 | 0 | 1 owner_review two_values; 5 needs_correction |

"Not compared" rows sit in the excluded 2026-09-30 quarters. The cash leg follows the rate. Where both
sides are empty, production also has no value (for the PIK-only rows: the margin reading or a
non-loan row leaves production's rate empty too).

## Legs check

Where the all-in rate, the cash leg and the PIK rate are all set, cash + PIK equals all-in within
1e-9 (`tests/int_field_normalised_rate_legs.sql`). Result in this build: 0 failing rows. It checks
this layer's arithmetic only. It cannot fail on today's code and does not check the legs against
production.

## 2026-03-31: published loans with a rate

Evidence for the owner, not a change. Loans are rows production classes as `LOAN` (this layer has no
loan class of its own). Published rows on both sides.

| Fund | Published loans | All-in rate here | All-in rate in production | Spread, no rate here | Spread, no rate in production |
|---|---:|---:|---:|---:|---:|
| Ares | 1,022 | 935 | 935 | 22 | 22 |
| BCRED | 1,192 | 1,160 | 1,168 | 30 | 22 |
| Blue Owl | 778 | 0 | 9 | 401 | 439 |
| Apollo | 747 | 44 | 44 | 645 | 703 |
| HPS | 776 | 612 | 617 | 4 | 13 |

"Spread, no rate here" are the rows spec section 10 (base rate plus spread) would later fill. The
counts differ from those in spec section 10 (Blue Owl 448 loans, Apollo 615): that section counted
loans another way; not reconciled here.

## What was not checked

- Whether any agreeing rate is right. Both pipelines read the same tags; a mis-tagged rate agrees.
- Rates missing on both sides (both_empty): 25,358 published all-in rates, most of Blue Owl and
  Apollo.
- Whether production's text readings (maturity, identifier text, printed margin, reference-rate
  column, loan class) are right. Only up to 4 rows per group were opened.
- Whether the Ares PIK-only rows production does read as coupons are coupons. They agree.
- The reference rate type and source, the floor, the coupon type (second spec).
- Rates on rows on one side only (`cmp_row_set` handles those).
- The 2026-09-30 quarters in `cmp_excluded_quarter`.
