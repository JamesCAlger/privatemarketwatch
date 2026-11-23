# Owner review: rate readings (slice 4 Task 3)

Date: 2026-11-23. Build: branch `warehouse-dbt`, slice 4 Task 3. All counts are position rows of the five v0.5 funds,
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
- **The PIK-only readings do not see the row's text.** Production reads a PIK-only row as the whole coupon only on a
  loan row (`asset_category = LOAN`), and for a fund with both readings only where the page prints a fixed coupon with
  no reference rate (`pipeline/financial_conventions.py`, `prepare`, table `typed`: `pik_is_coupon`, `pik_is_margin`).
  Those are printed-text features, not loaded in this slice. Here a fund with one reading applies it to every
  `pik_tag_only` row (controller ruling); a fund with two is a rule conflict (section 3).
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

What it does: on a `pik_tag_only` row the PIK rate is the whole coupon: all-in = PIK rate, kind `all_in`; cash leg
left empty (`pik_only_coupon`); spread left empty (`pik_is_coupon`). Source: `prepare`, `pik_is_coupon` branch.

| Fund | Rows given the coupon reading | Per quarter |
|---|---|---|
| Ares | 1,195 | 52, 58, 59, 59, 68, 71, 65, 76, 80, 74, 72, 70, 80, 76, 79, 74, 82 (2022-09-30 to 2026-09-30) |
| Apollo | 62 | 1, 5, 3, 2, 2, 5, 3, 4, 7, 5, 5, 6, 6, 8 (2023-06-30 to 2026-09-30) |

Assumption: every such row is a loan with a fixed PIK coupon. Production also requires the loan test; not checked
here. "Is a loan" is not a tagged row feature in `int_context_feature` or `int_source_row` (production's
`asset_category` is derived from text), so it is not a condition.

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Ares | 0001628280-26-067383 c-103 | PIK 0.09 [9.00] | all-in 9.00, PIK 9.00 |
| Ares | 0001628280-26-067383 c-1018 | PIK 0.20 [20.00] | all-in 20.00, PIK 20.00 |
| Apollo | 0001193125-26-449955 C_01681cb4-... | PIK 0.125 [12.50] | all-in 12.50, PIK 12.50 |

### 2.3 `pik_only_is_coupon` and `pik_only_is_margin` together: Blue Owl, HPS (rule conflict)

The two rules tie (same priority, same feature, no parameter, no dates). Controller ruling: neither is picked; the rows
are `rule_conflict`: interest rate, cash leg and spread unresolved, no value. The PIK rate itself is still normalised.
Production separates the two by printed text: a reference rate present means margin (spread = PIK rate, interest rate
unresolved); printed Fixed with no reference rate means coupon; loan rows only (`financial_conventions.py` `prepare`).
Waits for the text spec.

| Fund | Rows (all published) | Per quarter |
|---|---|---|
| Blue Owl | 460 | 25, 29, 29, 29, 29, 31, 32, 26, 28, 32, 33, 35, 35, 34, 33 (2023-03-31 to 2026-09-30) |
| HPS | 168 | 2, 7, 10, 14, 18, 18, 20, 13, 17, 14, 12, 13, 10 (2023-06-30 to 2026-06-30) |

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Blue Owl | 0001812554-26-000060 c-249 | PIK 0.0575 [5.75] | PIK 5.75; rate, cash, spread unresolved rule_conflict |
| Blue Owl | 0001812554-26-000060 c-250 | PIK 0.0625 [6.25] | same |
| HPS | 0001628280-26-056772 c-368 | PIK 0.05 [5.00] | same |

### 2.4 `printed_margin_cash_plus_pik` (wrapper `printed_margin_reading: cash_plus_pik`): Blue Owl, Apollo

What production does (`pipeline/bdc_xbrl_html_bridge.py`, `apply_ixbrl_field_status_overlay`, last block): on a loan
row with a printed reference rate, spread > 0 and PIK > 0, where the printed total margin equals spread + PIK within
0.011 and differs from the spread alone, the stored spread is spread + PIK (label `basis_spread:cash_plus_pik_margin`);
`pik_rate` unchanged. Otherwise the spread stays as filed. The printed margin is text, not read here, so the rule is
never decided: the spread is `unresolved`, `feature_missing` on every row with a spread and a PIK rate.

| Fund | Rows (spread and PIK both read) |
|---|---|
| Blue Owl | 321 (9 to 28 a quarter, 2023-03-31 to 2026-09-30) |
| Apollo | 219 (2 to 29 a quarter, 2023-03-31 to 2026-09-30) |

| Fund | Filing, context | Tagged | Stored |
|---|---|---|---|
| Blue Owl | 0001812554-26-000060 c-156 | spread 0.03 [3.00]; PIK 0.0275 [2.75] | PIK 2.75; spread unresolved |
| Blue Owl | 0001812554-26-000060 c-104 | spread 0.01 [1.00]; PIK 0.08 [8.00] | PIK 8.00; spread unresolved |
| Apollo | 0001193125-26-449955 C_1803cf83-... | spread 0.035 [350]; PIK 0.02 [2.00] | PIK 2.00; spread unresolved |

### 2.5 Blue Owl: no rate reading

Blue Owl declares no `filed_rate_reading` and files no interest-rate tag on any position. Its interest rate is never
set: 11,483 rows `absent` (no tag), 460 `rule_conflict` (section 2.3); `rate_kind` is `unresolved` on all 11,943. This
is the expected result, not a defect.

## 3. Two wrapper entries not built (need a procedure)

| Entry | Fund | What it would do | Rows it would touch |
|---|---|---|---|
| `rate_only_contexts adopt_adjacent` | Ares | Move the rate, spread and PIK facts of a rate-only context onto the adjacent value context (`pipeline/source_encodings.py` `adopt_rate_only_contexts`) | 7 pairs: 2023-12-31 1, 2025-03-31 1, 2025-06-30 3, 2025-09-30 2 (all takers published positions; approximation, `q_t3_adopt_adjacent.sql`) |
| `pik_margin_reading whole_coupon` | HPS | On a loan printed '<benchmark> + m PIK c %', store the printed coupon as the PIK rate (cash leg 0) (`pipeline/whole_coupon_pik.py` `apply`, `parse`) | about 171 rows over 14 quarters (0 to 28 a quarter), 86 of them with a rate tag; 3 listed exceptions (approximation of the printed grammar, `q_t3_whole_coupon.sql`) |

Neither can be a plain row-feature rule: one pairs two contexts, the other parses printed text. Rows of the second that
carry no rate tag overlap the HPS rule-conflict rows of section 2.3.

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
PIK rate is such a value), PIK rate 20, spread 68.

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
3. The 628 Blue Owl and HPS PIK-only rows: wait for the text spec, or a dated wrapper rule.
4. Values filed above 1 in a ratio unit (section 4): production's size rule, a filer rule per filing, or leave
   unresolved.
5. The two procedures of section 3.
