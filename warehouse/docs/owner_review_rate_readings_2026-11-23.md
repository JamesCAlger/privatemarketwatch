# Owner review: rate readings (slice 4 Task 3)

Date: 2026-11-23. Build: branch `warehouse-dbt`, slice 4 Task 3; PIK-only readings changed by the controller ruling
of 2026-11-23 in Task 4 (sections 1, 2.2, 2.3, 6). All counts are position rows of the five v0.5 funds,
all quarters, published or not, from `int_field_rule` / `int_field_normalised`. Queries:
`warehouse/scripts/slice4/q_t3_*.sql`.

What this file is not: agreement with production was not tested here (Task 4). Nothing here shows a stored rate is
right; a rule that reads a rate the same way production does would make the same mistake.

## 1. Assumptions every rate rule rests on

- **All quarters.** No rate rule in the wrapper copies carries a date. Every rule loads as `assumed_all_quarters` and
  is applied to every quarter of the fund (2022-09-30 to 2026-09-30). Nobody has checked that the filer kept the same
  convention in every quarter.
- **Scale.** A rate, PIK rate or spread filed in a ratio unit (`pure`, or `utr:Rate`, which is given the same unit kind
  by controller ruling) is read as a fraction and multiplied by 100 (`fraction_to_percent`, global default). A filed
  value above 1 is not rescaled by its size: it is left `unresolved`, reason `scale_not_decided` (section 4).
  Residual risk: a value tagged as a percent and at or below 1 (for example a 0.75 percent PIK rate tagged 0.75) passes
  as a fraction and becomes 75 percent. Measured: 0 filed values between 0.5 and 1 on the five funds; 0 normalised
  values outside 0 to 40 percent. That bound does not catch a 0.25 percent tagged 0.25 (stored as 25).
- **PIK-only rows carry no rate until printed text is read** (controller ruling 2026-11-23, slice 4 Task 4; replaces
  the Task 3 assumption that a fund with one PIK-only reading applies it to every `pik_tag_only` row). Production reads
  a PIK-only row as the whole coupon only on a loan row (`asset_category = LOAN`, a text class), and for a fund with
  both readings only where the page prints a fixed coupon with no reference rate (`pipeline/financial_conventions.py`,
  `prepare`, table `typed`: `pik_is_coupon`, `pik_is_margin`). Neither input is read here. Both actions now name
  `unread_input` `printed_rate_type_and_loan_class` in `seeds/action_field.csv`, so every PIK-only row is `unresolved`,
  reason `text_not_read`, on the all-in rate, its cash leg and the spread. The PIK rate itself is still read and
  normalised. Rows per fund (all quarters): Ares 1,195, Apollo 62, Blue Owl 460, HPS 168 (1,885). The Blue Owl and HPS
  rows were a rule conflict; the existing resolution order puts an unread input before a conflict, so they are now
  `text_not_read` too (rule conflicts on rate fields: 0). The comparison showed why: on Ares, 838 rows that production
  classes as preferred or common equity or a fund were given a PIK dividend as an all-in interest rate; on Apollo, 3 rows
  printed as a floating margin ('S+450 PIK') were given the margin as the all-in rate.
- **`pik_tag_only`** is production's PIK-only test without the loan test: a PIK rate above zero read, no interest-rate
  or cash-pay tag with a value (a nil-only tag does not count, production skips nil facts), no spread.
- **Cash leg.** Follows production's code on this branch: set only where a PIK rate is read (all-in less PIK), left
  empty otherwise. Production's changelog of 2026-11-13 says PIK-only coupons get cash 0; that change is not in the
  code here. "Cash = all-in when no PIK is read" is an open owner decision.

## 2. Every loaded rate rule

Rows per quarter are listed in `q_t3_rule_rows.sql` output; totals here.

### 2.1 `rate_is_all_in` (wrapper `filed_rate_reading: all_in`): Ares, BCRED, Apollo, HPS

What it does: the interest-rate tag is the all-in rate (times 100). Cash leg = all-in less the PIK rate where a PIK
rate is read, else left empty (`no_pik_read`). A PIK rate above the tag by more than 0.01 leaves both unresolved
(`pik_above_rate`, as production). Source: `financial_conventions.py` `prepare`, tables `conventions` (rate_kind) and
`calculated` (all_in, cash).

| Fund | Rows it decides | All-in stored | Cash leg stored | scale_not_decided | pik_above_rate | values_differ |
|---|---|---|---|---|---|---|
| Ares | 13,685 (17 quarters, 611 to 935 a quarter) | 13,002 | 1,227 | 669 | 13 | 1 |
| BCRED | 23,270 (16 quarters, 1,034 to 1,871) | 23,269 | 829 | 1 | 0 | 0 |
| Apollo | 325 (15 quarters, 5 to 42) | 317 | 12 | 6 | 2 | 0 |
| HPS | 6,562 (14 quarters, 295 to 644) | 6,559 | 669 | 3 | 0 | 0 |

Examples (tag value, printed text in brackets, stored):

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Ares | 0001628280-26-067383 c-1001 | rate 0.0876 [8.76]; spread 0.05 [5.00] | all-in 8.76; cash empty (no PIK) |
| BCRED | 0001803498-26-000048 c-100 | rate 0.0963 [9.63]; spread 0.0575 [5.75] | all-in 9.63 |
| Apollo | 0001193125-26-449955 C_05e0345a-... | rate 0.0959 [9.59] | all-in 9.59 |
| HPS | 0001628280-26-056772 c-104 | rate 0.0830 [8.30]; spread 0.0613 [6.13] | all-in 8.30 |

### 2.2 `pik_only_is_coupon` alone (wrapper `pik_only_tag_reading: coupon`): Ares, Apollo

Changed by the controller ruling of 2026-11-23 (slice 4 Task 4). The rule loads as before, but its action names
`unread_input` `printed_rate_type_and_loan_class`: it needs the loan class and the printed rate type, which no model
reads yet. So it never decides a row. Every `pik_tag_only` row is `unresolved`, reason `text_not_read`, on the all-in
rate, its cash leg and the spread; the PIK rate is normalised as before. The coupon arithmetic (all-in = PIK rate,
kind `all_in`, cash and spread empty) stays in `int_field_normalised` and is unit-tested; clearing `unread_input` (text
spec) switches it back on.

| Fund | Rows now text_not_read | Per quarter |
|---|---|---|
| Ares | 1,195 | 52, 58, 59, 59, 68, 71, 65, 76, 80, 74, 72, 70, 80, 76, 79, 74, 82 (2022-09-30 to 2026-09-30) |
| Apollo | 62 | 1, 5, 3, 2, 2, 5, 3, 4, 7, 5, 5, 6, 6, 8 (2023-06-30 to 2026-09-30) |

What the unconditional reading (Task 3) did against production, published rows compared (`cmp_rate`, before the
ruling; the 2026-09-30 quarter is not compared):

| Fund | Agreed with production | Wrong | Other |
|---|---:|---:|---:|
| Ares | 273 | 838: rows production classes preferred (658), common equity (171) or fund (9) got a PIK dividend as an all-in interest rate; production has no rate | 2: production corrected the rate |
| Apollo | 51 | 3: two loans printed 'S+450 PIK' and 'S+610 Cash (includes 5.97% PIK)' got the margin as the all-in rate | 0 |

After the ruling the 273 + 51 agreeing rows are `new_empty` in the comparison (production has the rate, this layer
does not); the 838 + 3 wrong rows are `both_empty`.

### 2.3 `pik_only_is_coupon` and `pik_only_is_margin` together: Blue Owl, HPS

Before the ruling of 2026-11-23 the two rules tied (`rule_conflict`). Both actions now need an unread input, and the
resolution order (`int_field_rule`, `top`) puts `text_not_read` before `rule_conflict`, so these rows are
`text_not_read` like the single-rule funds; not special-cased. Rate-field rule conflicts: 0. Interest rate, cash leg
and spread unresolved, no value; the PIK rate is still normalised. Production separates the two by printed text: a
reference rate present means margin (spread = PIK rate, interest rate unresolved); printed Fixed with no reference rate
means coupon; loan rows only (`financial_conventions.py` `prepare`). Waits for the text spec.

| Fund | Rows (all published) | Per quarter |
|---|---|---|
| Blue Owl | 460 | 25, 29, 29, 29, 29, 31, 32, 26, 28, 32, 33, 35, 35, 34, 33 (2023-03-31 to 2026-09-30) |
| HPS | 168 | 2, 7, 10, 14, 18, 18, 20, 13, 17, 14, 12, 13, 10 (2023-06-30 to 2026-06-30) |

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Blue Owl | 0001812554-26-000060 c-249 | PIK 0.0575 [5.75] | PIK 5.75; rate, cash, spread unresolved text_not_read |
| Blue Owl | 0001812554-26-000060 c-250 | PIK 0.0625 [6.25] | same |
| HPS | 0001628280-26-056772 c-368 | PIK 0.05 [5.00] | same |

### 2.4 `printed_margin_cash_plus_pik` (wrapper `printed_margin_reading: cash_plus_pik`): Blue Owl, Apollo

What production does (`pipeline/bdc_xbrl_html_bridge.py`, `apply_ixbrl_field_status_overlay`, last block): on a loan
row with a printed reference rate, spread > 0 and PIK > 0, where the printed total margin equals spread + PIK within
0.011 and differs from the spread alone, the stored spread is spread + PIK (label `basis_spread:cash_plus_pik_margin`);
`pik_rate` unchanged. Otherwise the spread stays as filed. The printed margin is text that no model reads yet (marked
in data: `seeds/action_field.csv`, column `unread_input` = `printed_total_margin`), so the rule is never decided: the
spread is `unresolved`, reason `text_not_read`, on every row with a spread and a PIK rate (controller ruling, fix round
1; ceiling 540). It is not a missing row feature: `feature_missing` stays an error class with ceiling 0.

| Fund | Rows (spread and PIK both read) | Per quarter |
|---|---|---|
| Blue Owl | 321 | 9, 13, 16, 22, 28, 28, 25, 16, 19, 23, 25, 22, 25, 28, 22 (2023-03-31 to 2026-09-30) |
| Apollo | 219 | 5, 4, 2, 4, 7, 6, 10, 15, 17, 24, 29, 21, 28, 23, 24 (2023-03-31 to 2026-09-30) |

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Blue Owl | 0001812554-26-000060 c-156 | spread 0.03 [3.00]; PIK 0.0275 [2.75] | PIK 2.75; spread unresolved |
| Blue Owl | 0001812554-26-000060 c-104 | spread 0.01 [1.00]; PIK 0.08 [8.00] | PIK 8.00; spread unresolved |
| Apollo | 0001193125-26-449955 C_1803cf83-... | spread 0.035 [350]; PIK 0.02 [2.00] | PIK 2.00; spread unresolved |

### 2.5 Blue Owl: no rate reading

Blue Owl declares no `filed_rate_reading` and files no interest-rate tag on any position. Its interest rate is never
set: 11,483 rows `absent` (no tag), 460 `text_not_read` (section 2.3; `rule_conflict` before the ruling of 2026-11-23); `rate_kind` is `unresolved` on all 11,943. This
is the expected result, not a defect.

## 3. Two wrapper entries not built (need a procedure)

| Entry | Fund | What it would do | Rows it would touch |
|---|---|---|---|
| `rate_only_contexts adopt_adjacent` | Ares | Move the rate, spread and PIK facts of a rate-only context onto the adjacent value context (`pipeline/source_encodings.py` `adopt_rate_only_contexts`) | 7 pairs: 2023-12-31 1, 2025-03-31 1, 2025-06-30 3, 2025-09-30 2 (all takers published positions; approximation, `q_t3_adopt_adjacent.sql`) |
| `pik_margin_reading whole_coupon` | HPS | On a loan printed '<benchmark> + m PIK c %', store the printed coupon as the PIK rate (cash leg 0) (`pipeline/whole_coupon_pik.py` `apply`, `parse`) | about 171 rows over 14 quarters (0 to 28 a quarter), 86 of them with a rate tag; 3 listed exceptions (approximation of the printed grammar, `q_t3_whole_coupon.sql`) |

Neither can be a plain row-feature rule: one pairs two contexts, the other parses printed text. Rows of the second that
carry no rate tag overlap the HPS PIK-only (`text_not_read`) rows of section 2.3.

## 4. Values whose scale is not decided (filed above 1 in a ratio unit)

These are not rescaled. A rule that decided scale from the size of the number would be a value-size rule and needs a
filer rule with evidence from the filing.

| Fund | Field | Quarter | Unit | Rows | Filed range |
|---|---|---|---|---|---|
| Ares | interest rate | 2022-09-30 | utr:Rate | 1 | 6.00 |
| Ares | interest rate | 2022-12-31 | utr:Rate | 8 | 3.75 to 9.29 |
| Ares | interest rate | 2023-09-30 | pure | 12 | 8.57 to 12.50 |
| Ares | interest rate | 2023-09-30 | utr:Rate | 645 | 3.61 to 16.43 |
| Ares | interest rate | 2026-06-30 | utr:Rate | 3 | 9.48 to 9.91 |
| Ares | PIK | 2026-06-30 | utr:Rate | 2 | 1.25 to 2.88 |
| Ares | spread | 2023-03-31 | utr:Rate | 1 | 8.00 |
| BCRED | interest rate | 2023-12-31 | pure | 1 | 11.45 |
| BCRED | PIK | 2023-12-31 | pure | 1 | 4.00 |
| Blue Owl | PIK | 2023-06-30, 2023-09-30, 2023-12-31 | pure | 3, 3, 2 | 6.25 to 12.00 |
| Apollo | interest rate | 2024-06-30 | pure | 6 | 2.75 to 6.90 |
| Apollo | spread | 2025-12-31, 2026-03-31 | pure | 32, 31 | 2.25 to 7.50 |
| HPS | PIK | 2024-06-30, 2025-12-31, 2026-03-31 | pure | 1, 4, 4 | 5.75 to 10.00 |
| HPS | spread | 2023-03-31 | pure | 5 | 5.00 to 8.25 |

Totals unresolved `scale_not_decided` (normalised layer): interest rate 679 (and its cash leg 679; includes rows whose
PIK rate is such a value), PIK rate 20, spread 68. The table lists 69 spread rows (1 + 63 + 5); one of them is `text_not_read`, which takes precedence over `scale_not_decided`, so 68 are scale rows (checked by query, `scripts/slice4/q_ff_counts.sql`).

Examples, printed text beside the tag:

| Fund | Filing, context | Field | Tagged | Printed | Other rates on the row |
|---|---|---|---|---|---|
| Ares | 0001287750-23-000045 c-1015 | rate | 13.00 utr:Rate | 13.00 | spread 0.045 [4.50] |
| Ares | 0001628280-26-050307 c-36 | rate | 9.48 utr:Rate | 9.48 | PIK 2.88 [2.88]; spread 0.0575 [5.75] |
| Ares | 0001628280-26-050307 c-36 | PIK | 2.88 utr:Rate | 2.88 | rate 9.48; spread 0.0575 |
| Ares | 0001287750-23-000021 i5b1a2a3... | spread | 8.00 utr:Rate | 8.00 | rate 0.1319 [13.19] |
| BCRED | 0001803498-24-000007 c-3847 | rate | 11.45 pure | 11.45 | PIK 4.00 [4.00]; spread 0.06 [6.00] |
| Blue Owl | 0001812554-24-000014 c-1418 | PIK | 12.00 pure | 12.00 | none |
| Apollo | 0000950170-24-094137 C_86104ef9-... | rate | 6.10 pure | 610 | PIK 0.01 [1.00] |
| Apollo | 0001193125-26-215667 C_1f3d3848-... | spread | 5.00 pure | 500 | none |
| HPS | 0001628280-26-033248 c-372 | PIK | 6.50 pure | 6.50 | rate 0.1046 [10.46] |
| HPS | 0001838126-23-000040 i8be22cc... | spread | 8.25 pure | 8.25 | rate 0.1306 [13.06] |

In every example the printed number equals the tag read as a percent (Apollo prints basis points: 610 for 6.10, 500
for 5.00). Next to each, the same filer tags its other rates as fractions. So the filers mix scales inside one filing.

What production does with these values (`pipeline/staging_bdc.py`, `_prepare_bdc`, the `interest_rate`, `basis_spread`
and `pik_rate` columns; and CTE `unified_pik_fixed`): a value below 0 is dropped; at or below 0.50 times 100; at or
above 50 divided by 100; between 0.50 and 50 kept as a percent. A PIK rate of 20 or more above the rate is divided by
100. That is a value-size rule. On these rows production would store the printed percent. Adopting it, or a filer rule
listing the filings, is an owner decision.

## 5. Maturity dates before the report date (as filed, not changed)

6 rows, all Apollo, one loan: Heubach Holdings USA LLC first lien term loan, maturity 2024-04-30, carried in the
filings for 2024-06-30, 2024-09-30, 2024-12-31, 2025-03-31, 2025-06-30, 2025-09-30 (all published). Whether the loan
was extended, matured unpaid or is mis-tagged was not checked.

## 6. Owner decisions open

1. Cash leg where no PIK rate is read: empty (as production's code) or equal to the all-in rate (the brief).
2. PIK-only coupons: cash leg empty (code on this branch) or 0 (production changelog 2026-11-13, not in the code).
   Moot until item 3 is settled: no PIK-only row gets a coupon now.
3. PIK-only rows carry no rate until printed text is read (controller ruling 2026-11-23; replaces the earlier item on
   the 628 Blue Owl and HPS rows). Rows per fund, all quarters: Ares 1,195, Apollo 62, Blue Owl 460, HPS 168. Where
   the unconditional coupon reading of Task 3 had been applied (published rows compared with production): Ares agreed
   273, wrong 838 (non-loan rows given a PIK dividend as a rate), 2 corrected by production; Apollo agreed 51, wrong 3
   (a printed floating margin given as the rate). Blue Owl and HPS were never read (conflict), 0 and 0. Options: wait
   for the text spec (loan class, printed rate type), or a dated, filer-level rule with evidence.
4. Values filed above 1 in a ratio unit (section 4): production's size rule, a filer rule per filing, or leave
   unresolved.
5. The two procedures of section 3.
6. The 540 spread-with-PIK rows of Blue Owl (321) and Apollo (219) under `printed_margin_cash_plus_pik` (section 2.4,
   per-quarter counts there): spread unresolved `text_not_read` until the printed total margin is read (text spec), or
   another reading. Production stores spread + PIK where the printed margin says so and the filed spread otherwise.
7. `rate_is_cash_leg` with no PIK rate read (no fund of the five declares it; 0 rows): here the all-in rate is left
   unresolved (`cash_leg_without_pik`). Production (`financial_conventions.py` `prepare`, the plain-tag branch before
   the fund reading) stores the tag as the all-in rate when the row text names no PIK (`names_pik`), for every fund
   whatever its reading. Leaving it unresolved is a choice made because the text is not read, not a reproduction.
   The same branch gives kind all_in to a plain rate tag with no PIK in a fund with no reading; on the five funds that
   is 0 rows (the only fund with no reading files no rate tag).
