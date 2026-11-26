# Baseline: rate text, slice R phase 2 (2026-11-26)

Branch `warehouse-text-spec`. Builds on `baseline_text_rates_phase1_2026-11-26.md` (sections 12 to 14) and the agent
run `baseline_text_rates_agent_run_2026-11-26.md` (run of record `text_runs/2026-11-26_rates_run3`). Queries:
`scripts/text/q_s0_*.sql` to `q_s6_*.sql`. No model call, no network.

**Proposals only, nothing published.** The agent's rules are loaded as seeds and read into proposal models that no
spine, staging or mart model reads; no rule was written to a wrapper. **No page was read by a person.** Passing a check
means the proposal is consistent with the filer's tags, its footnote legend and public rate series. It does not mean a
value is correct.

**Fix round 1 (review of 14c870e2) changed the verdict grain, the rate names, identity a, the contradiction rule and
the level check: section 10 holds where it disagrees with sections 1 to 9.**

Funds: Ares (0001287750), BCRED (0001803498), Blue Owl (0001812554), Apollo (0001837532), HPS (0001838126).

## 1. What was built

| Object | Decides |
|---|---|
| `scripts/text/proposals_to_seeds.py` | Writes the three proposal seeds from a run folder (stdlib, sorted, LF) |
| seeds `text_proposed_column`, `text_proposed_shape_role`, `text_proposed_code` | The proposals of run 3, both option orders side by side, `same_in_both_orders` |
| seeds `base_rate_fred`, `base_rate_series` | The FRED series downloaded 2026-11-26 (now in `_seeds.yml`, hash test, `-text`) |
| macro `base_rate_name` | A printed rate name or abbreviation to the base-rate vocabulary (same rules as the script) |
| `int_text_rate_proposed` | Each cell of the 31 proposed columns read with the proposed roles of its shape: one row per position, unit and number |
| `int_text_rate_proposed_position` | The read values per position (agreeing values only), beside the tags |
| `int_text_check_number_tag` | Each read number against the tag of the same field on the same position |
| `int_text_check_leg_arithmetic` | The leg identities per position |
| `int_text_base_rate_window` | Per report date and rate: the series range over the trailing 190 days, tolerance, state |
| `int_text_check_base_level` | Implied base against the proposed rate's window and every other rate's |
| `int_text_check_base_level_quarter` | Per code mapping and quarter: confirmed, discriminating, contradicted |
| `int_text_check_code_legend` | Per code mapping and filing: the filing's own legend |
| `int_text_proposal_verdict` | Per proposed column, shape and code: checks and verdict |

The proposal models read `int_text_cell`, `int_page_position`, `int_field_normalised` (tags before corrections),
`int_text_check_legend`, `int_text_check_column_tags` and `int_text_column_unit`; none reaches `stg_holdings` or a
`cmp_*` model (pytest `test_text_models_no_production.py`).

## 2. Proposals as seeds

31 columns, 284 shapes (385 role rows), 134 codes. Not the same in both orders: 1 column (Blue Owl "Interest",
`rate_terms` / `spread`), 7 shapes (the 6 of the agent-run note plus Blue Owl's "—%" share column, whose one role does
not fit a shape with no `#`), 2 codes (Apollo `T`: MUTKCALM / TONAR; Apollo `N`: cannot_tell / NIBOR).

Name normalisation: CDOR is checked as CORRA and BBSY as BBSW (their only series is the same OECD proxy;
`rate_name_note` says so). So one Apollo code answered CORRA in one order and CDOR in the other counts as the same.
Mapped to no series: CIBOR (BCRED, 4 units), SORA and "Bloomberg Short Term Bank Yield Index" (HPS), "CAD Base Rate"
(Ares), and the not-a-code words. Ares "Base Rate" was answered "Base Rate (prime/base rate)" and normalises to PRIME
(judgement call 6).

Two proposed shapes match no shape unit (Apollo, 1 position each: the bundle's 40-shape cap); every other proposed shape
matches its unit upper-cased.

## 3. The proposed read and the per-row checks

### 3.1 Positions read, per field (positions with a value; agreeing values only)

| | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| Positions with a proposed cell | 15,233 | 23,551 | 9,672 | 8,028 | 6,804 |
| spread | 13,658 | 22,668 | 8,445 | 7,379 | 6,312 |
| floor | 0 | 0 | 0 | 7,319 | 0 |
| all-in rate | 13,689 | 23,268 | 0 | 7 | 6,568 |
| cash rate | 0 | 0 | 0 | 3 | 0 |
| PIK rate | 2,807 | 1,111 | 652 | 292 | 695 |
| PIK spread | 0 | 3 | 120 | 0 | 188 |
| fixed rate | 0 | 431 | 0 | 324 | 73 |
| code with a rate that has a series | 13,655 | 22,651 | 8,674 | 7,380 | 6,479 |
| code with no series (CIBOR, SORA, BS, CAD Base Rate) | 2 | 15 | 0 | 0 | 21 |
| a field read twice with two values | 0 | 0 | 0 | 2 | 0 |

Rows not read (`int_text_rate_proposed` status): shape_unstable 90 rows (BCRED 47, Blue Owl 33, Apollo 10); no_proposal
4 (Apollo); not_a_rate_role 5,730 (Blue Owl's two share-of-net-assets columns); code_unstable 5, not_a_code 7 (Apollo);
no_value 1,615 ("N/A" and the like); role_cannot_tell 0. (number_not_parsed was removed in fix round 1: the number
pattern is digits only, so the cast cannot fail.)

### 3.2 Printed number against the tag (`int_text_check_number_tag`; tolerance 0.005)

| Fund | Field | Compared | Equal | Differs | No tag |
|---|---|---:|---:|---:|---:|
| Ares | all-in | 13,643 | 13,641 | 2 | 46 |
| Ares | PIK rate | 2,751 | 2,737 | 14 | 56 |
| Ares | spread | 13,646 | 13,643 | 3 | 12 |
| BCRED | all-in | 23,264 | 23,255 | 9 | 4 |
| BCRED | fixed rate (vs interest rate) | 374 | 374 | 0 | 57 |
| BCRED | PIK rate / PIK spread | 1,108 | 1,108 | 0 | 8 |
| BCRED | spread | 22,668 | 22,668 | 0 | 0 |
| Blue Owl | PIK rate / PIK spread | 772 | 766 | 6 | 0 |
| Blue Owl | spread | 8,129 | 8,127 | 2 | 316 |
| Apollo | spread | 7,146 | 7,144 | 2 | 233 |
| Apollo | fixed rate | 297 | 293 | 4 | 27 |
| Apollo | PIK rate | 286 | 284 | 2 | 10 |
| Apollo | all-in / cash | 7 | 4 | 3 | 3 |
| HPS | all-in | 6,562 | 6,562 | 0 | 6 |
| HPS | spread | 6,308 | 6,308 | 0 | 4 |
| HPS | PIK rate / PIK spread | 847 | 847 | 0 | 36 |
| HPS | fixed rate | 71 | 71 | 0 | 2 |

The 47 differences (`q_s6_differs.sql`), by kind:

- Ares "#% (#% PIK)" 13 (corrected in fix round 1): on all 13 rows the PIK tag equals the printed all-in rate (e.g.
  "10.35% (3.00% PIK)" with PIK tag 10.35) and there is no interest-rate tag: the filer tags the coupon under the PIK
  concept; Ares "#% PIK" 1 ("19.00% PIK" against 12.29). Ares spread "#%" 3 and all-in "#%" 2: one
  value printed, another tagged (6.00 / 5.75).
- BCRED all-in "#%" 9: printed coupon differs from the tag (e.g. 5.84 printed against 8.63 tagged; 2022-09-30).
- Blue Owl "SR+#% (#% PIK)" 6: the PIK tag equals the spread (5.75), not the printed PIK part (2.50). Blue Owl "SR+#" 2:
  the cell prints "SR + 0.0725", a fraction; the tag is 7.25 (the proposal reads 0.0725 as a percent).
- Apollo fixed "#%" 4: tag 0.07 against "10.36%" (cause not traced). Apollo "S+#, #% Floor" 2:
  "S+385" against a spread tag 0.38 and "S+450" against 0.50 (not a scale factor: neither tag is the printed
  spread over 10 or 100; cause not traced). Apollo "#% Cash plus #% PIK, #% Floor" 2 and "#% Cash plus #% PIK" 1:
  the cash part against the spine's cash leg (all-in tag less PIK): the filer tags the cash part as its interest rate,
  so the spine's all-in reading leaves a cash leg of 6.25 against a printed 12.50 (and 0 against 5.38). Apollo
  "S+225 Cash plus 2.75% PIK, 0.50% PIK" 2: two PIK numbers in one cell.

`interest_rate_cash` is derived by the spine for most filers (all-in less PIK), so agreement on cash rate is agreement
with the all-in and PIK tags, not with a separate filed number.

### 3.3 Leg arithmetic (`int_text_check_leg_arithmetic`)

Built, with printed values first and tags where a part is not printed, and only where at least one part is printed
(on tags alone the identity tests the filer and the spine's own derivation, which `int_rate_legs_check` already does):

| Identity | Rule | Tolerance |
|---|---|---|
| a_cash_plus_pik | cash + PIK = all-in | 0.011 |
| b_pik_le_all_in | PIK <= all-in | 0.011 |
| c_cash_le_all_in | cash <= all-in | 0.011 |
| d_floor_spread | all-in >= margin + floor (printed floor) | 0.011 |
| e_spread_split | tagged spread = printed spread + printed PIK spread, or = printed spread | 0.011 |
| f_printed_agree | a field read twice (two columns, or twice in one cell) gives one value | 0.005 |

The leg definitions are the spine's (rate reading: cash leg plus PIK equals all-in; a PIK above all-in is a fault); the
tolerance is 0.011, not the spine's 1e-9, because printed rates carry two decimals. In (d) the margin is the spread;
where a row has no spread but a printed PIK spread ("S+5.00% PIK"), the PIK spread. A fixed PIK leg is never added to
the margin (the all-in rate contains it, so leaving it out weakens the test without failing a right row); a PIK spread
beside a cash spread is not added either, because whether a tagged spread holds it differs by filer.

Not built: (d) on PIK-spread rows that also have a cash spread (see above); a check of the floor against the base rate
on its own (a floor is printed only at Apollo, which has no all-in tag); cash + PIK = all-in where all three are printed
in one cell (no shape prints all three).

| Fund | Identity | Rows | Pass | Fail |
|---|---|---:|---:|---:|
| Ares | a / b / c | 1,232 / 1,306 / 13,638 | 1,232 / 1,305 / 13,638 | 0 / 1 / 0 |
| BCRED | a / b / c | 831 / 839 / 23,262 | 830 / 839 / 23,259 | 1 / 0 / 3 |
| BCRED | f | 2 | 2 | 0 |
| Apollo | a / b / c | 7 / 13 / 7 | 4 / 13 / 7 | 3 / 0 / 0 |
| Apollo | d | 8 | 0 | 8 |
| Apollo | f | 2 | 0 | 2 |
| HPS | a / b / c | 672 / 700 / 6,540 | all | 0 |

No row of Blue Owl applies (no all-in rate printed or tagged, and its PIK spreads have no tagged total spread). (e)
applies to no row of any fund. The 18 failures (`q_s3_leg_fails.sql`; ceiling `int_text_leg_identity_fail` 18):

- Ares 2025-09-30, b: printed coupon 8.75, PIK tag 15.00.
- BCRED 2022-09-30, c (3): printed coupons 5.84, 6.87, 8.63 against all-in tags 8.63, 8.88, 9.83 (the same rows differ
  in 3.2). BCRED 2024-12-31, a: "8.75%" printed as the PIK rate (a PIK-only coupon) and as the all-in rate; the tags
  carry no PIK, so the tagged cash leg is the whole 8.75.
- Apollo, d (8): "S+400, 0.50% Floor" with an all-in tag 4.00, "S+500, 0.75% Floor" with 5.00, "S+550, 1.00% Floor"
  with 5.50, "S+675, 1.00% Floor" with 6.75 (2024-09-30: the all-in tag holds the spread), "S+250, 0.50% Floor" with
  0.50 and "S+515" / "S+550, 1.00% Floor" with 1.00 (2025-09-30 to 2026-06-30: the all-in tag holds the floor). Apollo,
  a (3): "12.50% Cash plus 6.25% PIK" (2025-06-30, 2025-09-30) and "5.38% Cash plus 5.38% PIK" (2026-09-30) whose
  all-in tag equals the cash part. Apollo, f (2): "S+225 Cash plus 2.75% PIK, 0.50% PIK" (2026-03-31, 2026-06-30).

These are tag faults or filer conventions found by the proposals, not faults in the proposals: on each failing row the
printed number is read as the agent proposed, and the tag disagrees with what the cell prints.

## 4. Base-rate level check

### 4.1 Window and series

`int_text_base_rate_window`: for each report date, the trailing 190 days (loans reset to a term rate fixed 1 to 6 months
earlier). A rate with a published daily series (SOFR, SONIA, PRIME, FEDFUNDS) uses it, and only it (SONIA's UK monthly
proxy is not used; the SOFR averages are not used: overnight SOFR over the window spans them). The other rates use
their monthly OECD 3-month interbank proxy, every month overlapping the window. Stale: last value more than 7 days old
(daily) or 62 days (monthly). EURIBOR and the UK proxy end 2026-01: EURIBOR is stale at 2026-06-30 and has no value at
2026-09-30 (58 BCRED, 30 HPS, 21 Ares tested rows have no series).

SOFR term premium: no term SOFR series exists here (licensed). The admissible upper edge of SOFR is raised by 0.26 (the
credit spread adjustment of 0.10 / 0.15 / 0.25 many loans add, plus rounding). It does not cover term SOFR running
above overnight SOFR while rates rose fast (2022): those rows stay outside, on purpose.

Floor binding: an implied base outside the range that equals the printed floor within 0.05 is `floor_binding`, above
or below the range (a floor above every window value, 2022, puts the implied base above). It fired on **no row**: the
only fund printing floors (Apollo) has no all-in rate to imply a base from.

### 4.2 Coverage

Rows tested need a proposed rate with a series, no PIK leg, a spread (printed, else tag) and an all-in rate (tag, else
printed). Proposed-rate rows by input state (`q_s4_base_inputs.sql`):

| Fund | usable | PIK | no all-in |
|---|---:|---:|---:|
| Ares | 12,173 | 1,482 | 0 |
| BCRED | 21,629 | 1,022 | 0 |
| Blue Owl | 0 | 566 | 8,108 |
| Apollo | 5 | 229 | 7,146 |
| HPS | 5,714 | 711 | 54 |

**Blue Owl and Apollo cannot be covered**: Blue Owl tags no all-in rate and prints none in the proposed columns;
Apollo tags an all-in rate on 5 of its coded positions (and those 5 are the d failures above, the tag holding the
spread). For them the code mappings rest on the legend alone.

### 4.3 Measurement first

Distance = implied base minus the nearest edge of the proposed rate's window, before any tolerance
(`q_s4_distance.sql`, every rate and quarter). SOFR, the largest group:

| Quarter | Rows | Inside the range | p90 | p98 | Within 0.30 | Within -0.30 / +0.56 (chosen) |
|---|---:|---:|---:|---:|---:|---:|
| 2022-09-30 | 315 | 0.42 | 0.71 | 0.83 | 0.73 | 0.77 |
| 2022-12-31 | 535 | 0.42 | 0.41 | 0.66 | 0.73 | 0.95 |
| 2023-03-31 | 874 | 0.40 | 0.22 | 0.40 | 0.95 | 0.98 |
| 2023-06-30 | 1,576 | 0.12 | 0.31 | 0.50 | 0.80 | 0.99 |
| 2023-09-30 | 1,950 | 0.13 | 0.27 | 0.35 | 0.91 | 0.99 |
| 2023-12-31 | 2,051 | 0.28 | 0.21 | 0.28 | 0.98 | 1.00 |
| 2024-03-31 to 2024-06-30 | 4,182 | 0.37 to 0.50 | 0.09 to 0.15 | 0.20 | 0.99 to 1.00 | 1.00 |
| 2024-09-30 | 2,206 | 0.71 | 0.00 | 0.11 | 0.99 | 0.99 |
| 2024-12-31 to 2026-06-30 | 18,467 | 0.73 to 0.99 | 0.00 | 0.00 to 0.06 | 1.00 | 1.00 |
| 2026-09-30 | 730 | 0.33 | 0.18 | 0.36 | 0.93 | 1.00 |

The upper tail in 2023 (p98 0.35 to 0.50) is the credit spread adjustment; the 2022 tail (p90 0.71) is term SOFR
above overnight SOFR during the hikes. The lower side is near 0 everywhere (p02 at most -0.22).

Other rates: LIBOR (OECD US proxy) 0.97 to 1.00 within ±0.60 in every quarter (the 2022-09-30 quarter 0.75 within
±0.30); EURIBOR, SONIA, PRIME, NIBOR, STIBOR, BKBM and CORRA from 2024 at or near 1.00 within 0.30; CORRA in 2022-2023
sits 0.2 to 0.6 above the proxy (p90 0.46 to 0.76: CDOR ran above the OECD Canada series), and 0.31 of its 2022-12-31
rows are outside even at 0.60.

Tolerance sensitivity (`q_s4_sensitivity.sql`; proposal-quarters with at least 10 tested rows: 168; floor binding
ignored):

| Tolerance (times 0.30 / 0.60) | Confirmed | Discriminating | Tested rows admissible |
|---|---:|---:|---:|
| 0 (range only, SOFR adjustment kept) | 72 | 26 | 87.5% |
| 0.5 (0.15 / 0.30) | 145 | 19 | 96.6% |
| 1 (0.30 / 0.60, chosen) | 163 | 20 | 99.2% |
| 2 (0.60 / 1.20) | 167 | 20 | 99.8% |

Chosen: the brief's starting values, 0.30 published and 0.60 proxy, plus 0.26 on SOFR's upper edge. Halving them fails
18 more proposal-quarters; doubling them passes the 2022 SOFR quarters the series cannot judge (term SOFR missing).
Discrimination barely moves with the tolerance (20 at 1, 26 at 0): the rates overlap in level, not by tolerance. **What
fails at the chosen tolerance** (the 5 of 168 proposal-quarters not confirmed): SOFR 2022-09-30 at Ares (0.69) and in
two BCRED units (0.79, 0.80); BCRED E 2022-09-30 (0.86); BCRED S 2022-12-31 (0.75, 12 rows). Rows outside the proposed
SOFR window over all quarters: Ares 54 of 10,076, BCRED 141 of 17,889, HPS 15 of 4,916.

### 4.4 Confirmed and discriminating, by fund and rate

Quarters with at least 10 tested rows (`q_s6_rate_summary.sql`); "alternatives" = rates admissible for more than 50% of
the rows, with the number of such quarters:

| Fund | Rate | Quarters | Confirmed | Discriminating | Tested / outside | Alternatives admissible |
|---|---|---:|---:|---:|---|---|
| Ares | SOFR | 17 | 16 | 0 | 10,076 / 54 | FEDFUNDS 17, LIBOR 17, BKBM 14, SONIA 13, CORRA 11, BBSW 10, NIBOR 10 |
| Ares | PRIME ("Base Rate") | 17 | 17 | 17 | 367 / 0 | none |
| Ares | LIBOR | 5 | 5 | 0 | 1,175 / 20 | BKBM, CORRA, FEDFUNDS, SOFR 5 |
| Ares | CORRA (CORRA, CDOR) | 11 | 11 | 0 | 222 / 4 | BKBM 9, KORIBOR 8, STIBOR 8, EURIBOR 6 |
| Ares | EURIBOR | 8 | 8 | 0 | 148 / 0 | KORIBOR 8, STIBOR 8, CORRA 6 |
| Ares | SONIA | 2 | 2 | 0 | 109 / 5 | SOFR, FEDFUNDS, LIBOR, BBSW 2 |
| BCRED | SOFR | 27 | 24 | 0 | 17,889 / 141 | FEDFUNDS 27, LIBOR 27, BKBM 23, SONIA 22 |
| BCRED | LIBOR | 7 | 7 | 0 | 2,549 / 44 | BKBM, CORRA, FEDFUNDS, SOFR 7 |
| BCRED | EURIBOR | 15 | 14 | 0 | 476 / 4 | STIBOR 15, KORIBOR 14, CORRA 11 |
| BCRED | SONIA (S) | 14 | 14 | 0 | 290 / 2 | FEDFUNDS, LIBOR, NIBOR, SOFR 14 |
| BCRED | CORRA | 2 | 2 | 0 | 130 / 5 | BKBM 2 |
| BCRED | PRIME | 3 | 3 | 3 | 117 / 6 | none |
| HPS | SOFR (SF) | 14 | 14 | 0 | 4,916 / 15 | FEDFUNDS 14, LIBOR 14, SONIA 13 |
| HPS | EURIBOR | 12 | 12 | 0 | 267 / 0 | KORIBOR 12, STIBOR 12, CORRA 7 |
| HPS | SONIA (SN) | 12 | 12 | 0 | 170 / 1 | FEDFUNDS, LIBOR, NIBOR, SOFR 12 |
| HPS | LIBOR | 2 | 2 | 0 | 139 / 0 | BKBM, CORRA, FEDFUNDS, SOFR 2 |

Rates with fewer than 10 tested rows in every quarter (Ares NIBOR, BBSW, BKBM, TONA; BCRED STIBOR, SARON, BKBM, NIBOR,
BBSW; HPS BBSW, CORRA, PRIME, NIBOR, STIBOR, TONA, BKBM): never confirmed, never contradicted.

- **Confirmed and discriminating: only the prime rate** (Ares "Base Rate" all 17 quarters; BCRED P 3 quarters). Prime
  sits 3 points above every other rate. Ares "Base Rate" is probably the alternate base rate (at or near prime): the
  check confirms a prime-like level, not which definition.
- **Confirmed, not discriminating: every other mapping.** SOFR cannot be told from fed funds in any quarter (the two
  move together within about 0.1) nor from the LIBOR proxy; from SONIA in 13 of 17 (Ares) and 22 of 27 (BCRED)
  quarters (2023-2026 SONIA ran within 0.5 of SOFR). EURIBOR cannot be told from STIBOR and KORIBOR (near 2.0 to 3.5
  together), nor from CORRA after 2024. SONIA (BCRED S, HPS SN) cannot be told from SOFR in any quarter, so this check
  does not settle phase 1's question whether BCRED's S is SONIA or SOFR (the legend does: section 5).
- **Fails:** the SOFR 2022 quarters above, and BCRED S 2022-12-31. Nothing confirmed for Blue Owl and Apollo (no rows).

## 5. Legend, per filing (`int_text_check_code_legend`)

| Fund | Agrees (filing-units / positions) | Mixed | No legend in filing |
|---|---|---|---|
| Ares | 0 | 0 | 146 / 13,655 |
| BCRED | 179 / 21,613 | 1 / 12 (S in 2022-12-31: SOFR and SONIA) | 9 / 1,026 |
| Blue Owl | 47 / 3,544 | 0 | 54 / 5,130 |
| Apollo | 65 / 6,800 | 0 | 63 / 580 |
| HPS | 116 / 6,479 | 0 | 0 |

No proposal contradicts a legend. HPS B=BBSY and the Blue Owl/HPS C=CDOR/CORRA transition legends, mixed in phase 1,
agree here because BBSY/BBSW and CDOR/CORRA normalise to one series name (judgement call 2).

## 6. Verdicts (`int_text_proposal_verdict`)

| Kind | accepted_by_check | needs_owner | unstable | contradicted | nothing_to_read |
|---|---:|---:|---:|---:|---:|
| Columns (31) | 26 (95,936 positions) | 4 (32,533) | 1 (1,416) | 0 | - |
| Shapes (284) | 146 (101,672) | 74 (5,872) | 7 (98) | 1 (3,875) | 56 (18,366) |
| Codes (134) | 70 (39,513) | 60 (18,856) | 2 (5) | 2 (515) | - |

Rules (model header): unstable = the orders differ; contradicted = a check disagrees on at least 5 rows and at least 10%
of its compared rows; accepted_by_check = a strong check confirms (at least 5 compared rows, 90% agreeing) and none
contradicts; needs_owner otherwise. Strong: column tags; number-tag; leg identities a, d, e; legend; a discriminating
base-level quarter. A confirmed but non-discriminating base level does not accept (`checks_weak`). Shapes without a
number are `nothing_to_read` (their code is judged as a code).

### 6.1 Contradicted (3; ceiling `int_text_proposal_contradicted` 3)

| Fund | Proposal | Positions | Check | Why |
|---|---|---:|---|---|
| BCRED | code SOFR in unit fc9493 (2022 tables) = SOFR | 331 | base level: 37 of 327 outside | 2022-09-30 and 2022-12-31: term SOFR above overnight SOFR. Legend agrees |
| BCRED | code SOFR in unit 4911ba (2022 tables) = SOFR | 184 | base level: 19 of 184 outside | the same quarters. Legend agrees |
| Apollo | shape "S+#, #% Floor" in unit b4ee19 = spread_bps, floor_pct | 3,875 | leg d: 5 of 5 rows fail | the all-in tag holds the spread or the floor (3.3). Number-tag: spread equal on 3,858 of 3,859 |

None of the three is shown to be a wrong proposal: two are limits of the series in 2022, one is the filer's tags.

### 6.2 Unstable (10)

- Column: Blue Owl "Interest" [0dd66c], rate_terms / spread (1,416 positions; the tag check would confirm either).
- Shapes: "#%" in a reference-rate-and-spread column, fixed_rate / spread_pct (BCRED [35d86f] 34, [16de07] 13; Blue
  Owl [256066] 19); Blue Owl "#% (#% PIK)" cash_rate / spread_pct (7); Blue Owl "—%" (19, role list does not fit);
  Apollo "S+# PIK" pik_spread / spread_bps (4); Apollo "#% Cash plus #% PIK, #% Floor" all_in / cash (2).
- Codes: Apollo T (MUTKCALM / TONAR, 4 positions), Apollo N (cannot_tell / NIBOR, 1).

### 6.3 Needs owner

Columns (4): Ares "Coupon" [1de53b] all_in_rate (15,233 positions: the all-in tag on 13,709 of 15,233 tagged rows, 0.89995;
the PIK tag on the rest, just under the 0.90 bar); the three reference-code columns,
Ares "Reference" [9ecddf] (13,657) and Blue Owl "Ref. Rate" [501a2d] (2,109) and [aceeb6] (1,534): no tag exists.

Codes (60), by why:
- Base level confirmed but not discriminating, no legend (Ares, 13,202 positions): SOFR 11,359, LIBOR 1,308, Euribor
  172, CORRA 144, SONIA 131, CDOR 88; BCRED S=SOFR in [fc9493] 22 (its one filing's legend is mixed).
- No legend, too few tested rows (under 10 in every quarter): Ares NIBOR 18, BBSY 17, BKBM 14, TONA 7.
- No legend and no testable row: Blue Owl SR=SOFR (3,407 and 1,343), L=LIBOR (208, 70), P (3); Apollo SONIA (208,
  153), N (3), and the not-a-code words "Equity plus" (3, 2) and "Variable" (2).
- Legend agrees on fewer than 5 positions and too few tested rows: BCRED B, CA, BB, P, S=SONIA, ST, SA, N, E, C (1 to 4
  positions each, 16 code proposals); Blue Owl P 26, SA 25, C 17, B 4 / 3 / 1, BB 1; Apollo SARON 12 / 3, K 6 / 4, T 3,
  NIBOR 1; HPS BB 2.
- No series: BCRED CI=CIBOR (8, 5, 1, 1); HPS SORA 13, BS 8; Ares "CAD Base Rate" 2; BCRED SORF=SOFR 1 (a typo, 1 row).

Shapes (74): every one has fewer than 5 compared rows on each number (72 of them with at most 4 positions), except Blue Owl's two share-of-net-assets "#%" shapes (4,333 and 1,397 positions: role pct_of_net_assets,
no rate check applies) and Apollo "S+# Cash plus #% PIK, #% PIK" (2 positions, the f failures). Full list:
`q_s5_not_accepted.sql`.

## 7. Tests and build

- Unit tests (`models/intermediate/_text_proposed.yml`): k-th number and statuses (`S+525, 0.50% Floor`, `5.38% Cash
  plus 5.38% PIK, 0.00% Floor`, `SOFR + 5.25%`, `S+1250` and `S+1,250`, basis points to percent, unstable, no proposal,
  cannot tell, no value); number-tag verdicts (tolerance edge); every leg identity, pass and fail, incl. the 0.011 edge
  and the PIK-spread margin; the base-rate window (190 days, monthly overlap, stale, no values, averages not used); the
  base-level verdicts incl. floor binding; the quarter's confirmed / discriminating / contradicted; the verdict rules.
- Keys and coverage: `tests/int_text_proposal_keys_unique.sql`; seed hashes: `tests/seed_base_rate_hash_matches.sql`.
- Baselines (measured): `int_text_proposal_contradicted` 3 (redefined in fix round 1, section 10),
  `int_text_leg_identity_fail` 18; `int_text_rate_proposed_number_not_parsed` 0 was removed in fix round 1.
- Full build (`dbt.ps1 build --threads 2`, log `scratch/2026-11-26_text_slice_r2/full_build.log`): `PASS=1081 WARN=125
  ERROR=0 TOTAL=1206` (was 997 / 123 / 1120; the 2 new warnings are the contradicted and identity-fail baselines).
- CI fixture (`ci/run_fixture_build.py`, local, new folder): step 4 `PASS=3`; build `PASS=673 WARN=5 ERROR=0
  TOTAL=678`; empty run `PASS=2`; unit-test and drift step `PASS=70`. The seeds load there; the proposal models build
  empty on the invented fund (the check that every proposed unit is a rate candidate is skipped under `ci_fixture`).
- pytests (`warehouse/pytests`): 180 passed.

## 8. Judgement calls and deviations

1. Grain of `int_text_rate_proposed`: one row per (position, unit, number_index), not per field: a cell can read the same
   field twice (2 Apollo cells print two PIK rates), and statuses that give no field still need a row. Fields are unique
   per (position, unit) on read rows except those 2.
2. CDOR and CORRA, BBSY and BBSW are one name each for stability and the legend (their only series is shared); the
   seed keeps the raw answers and a note.
3. Statuses added to the brief's five: not_a_rate_role (share-of-net-assets and other_number roles), code_unstable,
   not_a_code, no_value. A shape whose role list does not fit its `#` count is shape_unstable.
4. Shape stability is per shape (any number differing makes every number of the shape unread), not per number.
5. A PIK spread is compared with the PIK rate tag; a fixed rate with the interest rate tag.
6. Ares "Base Rate" normalises to PRIME from the agent's words "prime/base rate"; the level check then confirms and
   discriminates it in every quarter. It is probably the alternate base rate of US credit agreements (the greater of
   prime, fed funds + 0.50 and one-month term SOFR + 1.00), which sits at or near prime: the check confirms a prime-like
   level, not the definition.
7. The level check takes the all-in rate from the tag first, else the printed proposal (the brief says tagged). It adds
   11 usable rows (a printed all-in rate where no all-in tag exists).
8. Floor binding applies above and below the range (the brief said below): below cannot be explained by a floor, above
   is where a floor binds. It fired on no row.
9. The contradiction rule is "at least 5 rows AND at least 10%". The brief reads "5+ rows or 10%+"; the literal OR would
   contradict any large proposal with 5 outliers (SOFR at Ares: 54 of 10,076 outside) and any small one with one row.
   Under OR (measured on totals, `q_s7_doc_checks.sql`): 22 stable code proposals and 10 stable shapes would be
   contradicted, against 2 and 1 under AND. The model records the AND result.
10. A column's verdict uses its tag check only. The base level judges codes, not shapes: a failure there is laid on the
    code mapping, though a wrong spread reading would also move the implied base.
11. Leg identities a, d and e can confirm a shape; b, c and f can only contradict (inequalities and duplicates are weak
    confirmations).
12. Two `int_text_proposal_verdict` thresholds not in the brief: confirm at least 5 compared rows and 90% agreeing; a
    column tag contradiction needs a 0.50 dominant share.
13. `.gitattributes` (outside `warehouse/`) gains the two base-rate seeds as `-text`, as the brief asks.

## 9. Not known

- Whether any proposal is right on the printed page: no page was opened.
- Which rate a code stands for where rates overlap in level: the level check discriminates only prime. SOFR against fed
  funds is not decidable from public series.
- Blue Owl and Apollo code mappings: no all-in rate, so no level check; Blue Owl's SR and L have no legend in most
  filings.
- Term SOFR: not available, so 2022 SOFR quarters cannot be judged.

## 10. Fix round 1 (review of 14c870e2, 2026-11-26)

Reviewer queries `scripts/text/review_r3_*.sql` (not committed); queries of this round `scripts/text/q_s8_*.sql`,
`q_s9_*.sql`. Still proposals only, nothing published, no page read; passing is consistency, not correctness.

### 10.1 What changed

| # | Finding | Change |
|---|---|---|
| 1 | A multi-number shape was accepted when one number was checked | `int_text_proposal_verdict` gains kind `role` (unit, shape, number index, role) with its own evidence and verdict. A role with no check that can test it is `needs_owner`, reason `no_check_exists` (every floor; a number whose field is never tagged on its rows). A shape is `accepted_by_check` only when every role is; `partly_accepted` lists `roles_accepted` / `roles_not_accepted` |
| 2 | CDOR/CORRA and BBSY/BBSW were merged outside the level check | Four names in the seeds (script re-run), the proposed read, the legend check (macro `base_rate_name`) and the verdict; same-in-both-orders compares those names; a filing whose legend gives two names is `mixed`. The proxy mapping exists only as `proxy_series` inside `int_text_check_base_level` |
| 3 | Identity a restated the number-tag comparison | Every identity row carries `lhs_source`, `rhs_source`, `independence`, `counts_as_confirming`. a counts only with a printed cash leg and not all three parts printed; e always; b, c, d, f never (they can only contradict) |
| 4 | BCRED 2022-09-30 row shift | Traced in the filed layer (10.4); no model changed |
| 5 | Total failures on few rows passed | New verdict `contradicted_small`: a check failing on at least 2 rows AND at least half its compared rows (vars `text_verdict_small_min_rows`, `text_verdict_small_min_share`); never accepted |
| 6 | Currency bloc | `int_text_check_base_level_quarter.separates_currency_bloc` (with `best_other_currency_share`, `other_currency_admissible_rates`); reported, not an acceptance |
| 7 | Small items | `number_not_parsed` status and its baseline removed (unreachable); `int_text_check_number_tag` filters the interest-rate tag to rate kind all-in, as its header says; doc corrections in 3.2 and 8 |

### 10.2 Verdicts before and after

| Kind | Before (14c870e2) | After |
|---|---|---|
| Columns (31) | accepted 26, needs_owner 4, unstable 1 | accepted 26, needs_owner 4 (no_check_exists 3, below_bar 1), unstable 1 |
| Shapes (284) | accepted 146, needs_owner 74, unstable 7, contradicted 1, nothing_to_read 56 | accepted 116 (98,069 positions), partly_accepted 29 (1,264), needs_owner 71 (5,866), unstable 7, contradicted 1 (3,875), contradicted_small 4 (2,345), nothing_to_read 56 |
| Codes (134) | accepted 70, needs_owner 60, unstable 2, contradicted 2 | accepted 66 (32,993), needs_owner 59, unstable 3, contradicted 4 (663), contradicted_small 2 (6,372) |
| Roles (new) | - | below |

Roles by role type (count, positions of the role's shape in brackets):

| Role | accepted | no_check_exists | too_few_rows | contradicted | contradicted_small | other |
|---|---|---|---|---|---|---|
| spread_bps | 15 (925) | 22 (189) | 9 (51) | 1 (3,875) | 1 (2,339) | - |
| spread_pct | 71 (50,883) | 4 (150) | 30 (48) | - | 1 (2) | - |
| floor_pct | 0 | 37 (1,105) | - | 1 (3,875) | 1 (2,339) | unstable 1 (2) |
| all_in_rate_pct | 17 (43,512) | - | 8 (20) | - | - | unstable 1 (2) |
| cash_rate_pct | 0 | - | 1 (1) | - | 1 (2) | unstable 1 (7) |
| pik_rate_pct | 41 (5,487) | 4 (7) | 30 (63) | - | 3 (6) | unstable 2 (9) |
| pik_spread_pct | 9 (306) | - | 3 (5) | - | - | unstable 1 (4) |
| fixed_rate_pct | 7 (828) | - | - | - | - | unstable 3 (66) |
| pct_of_net_assets, other_number | - | - | - | - | - | role_not_a_rate 2 (5,730); unstable 1 (19) |

No floor is accepted anywhere: no filer tags a floor, and the floor identity (d) can only contradict. The 29
partly-accepted shapes are Apollo floor shapes (25 shapes, 1,114 positions: spread accepted, floor no_check_exists) and
Blue Owl "SR+#% (#% PIK)", "E+#% (#% PIK)" and two more (4 shapes, 150 positions: the PIK part accepted, the spread never
compared because no spread tag exists on those rows).

What moved from accepted:
- Shapes: 29 -> partly_accepted (above); Apollo "S+#, #% Floor" [8900b6] (2,339 positions) -> contradicted_small (its
  floor identity fails on all 3 rows that carry an all-in tag, the tag holding the floor; the spread equals its tag on
  2,337 of 2,338 rows).
- Codes: HPS B (now BBSY, 113 positions) and HPS C (CORRA, 35) -> contradicted. The legends define B as BBSW in seven
  filings to 2024-09-30, both names in 2024-12-31, BBSY from 2025; C as CDOR in nine filings to 2025-03-31, both in
  three, CORRA from 2026-03-31 (`q_s8_legend_bc.sql`). The agent gave the latest name; a dated rule is needed. Apollo
  S=SOFR in two units (3,969 and 2,403 positions) -> contradicted_small: the fund's only 5 rows with an all-in tag (3 and
  2 per unit) fall outside every window because that tag holds the spread (section 3.3); the legend agrees in 15
  filings.
- Codes, other moves: Blue Owl C [256066] (17 positions) needs_owner -> unstable (CORRA in one order, CDOR in the
  other). BCRED C stays accepted, now as CDOR.

### 10.3 Identity a and independence

Of 2,742 a rows, 2,739 have a tagged cash leg (the spine's all-in less PIK) and are `not_independent`: they restate the
number-tag equality and no longer confirm anything. The 3 independent rows (Apollo, printed "Cash plus PIK" pairs against
an all-in tag) all fail, so identity a confirms no role. Sides: a cash + PIK (lhs) against all-in (rhs); b PIK against
all-in; c cash against all-in; d all-in against margin + floor; e tagged spread against printed spread + PIK spread; f
printed against printed. b, c, d and f rows can only contradict. Failures unchanged: 18 (`int_text_leg_identity_fail`).

### 10.4 The BCRED 2022-09-30 row shift (finding, no fix)

Filing 0001803498-22-000021, printed rows 826 to 835 (`q_s9_shift.sql`, `q_s9_shift_rows.sql`). The placement is right;
the filer's tagging is shifted. Every fact is placed on the row it is printed on, and each position's fair value and
spread facts are on the position's own row, but the interest-rate fact printed on row r belongs to the context of the
position on row r-1. Three rows from the filed layer:

| Printed row | Row's cells (company, code, spread, rate) | Interest-rate fact placed on this row (value, context) | That context's position row |
|---|---|---|---|
| 826 | Cloudera, Inc.: L +, 3.75%, 6.87% | 6.87, ...4478a68a41766914abe2 | none (a context with no position) |
| 827 | Community Brands ParentCo, LLC: SOFR +, 5.75%, 8.88% | 8.88, ...40069ca3602a385a1f23 | 826 (Cloudera's position) |
| 828 | next company: 8.74% printed | 8.74, ...4d66aa5e1f5b8ee3ab16 | 827 (Community Brands) |

Context ...40069ca...'s fair value (53,696) and spread (3.75) facts are on row 826; only its interest rate sits on row 827.
Rows up to 825 and from 836 on are in step. Positions affected: 10 (rows 826 to 835). For 9 of them (826 to 834) the
spine's tagged interest rate is the next row's printed rate, a neighbour's rate; the position on row 835 has no
interest-rate tag; the rate printed on row 826 is tagged to a context with no position. The proposals read each printed
rate on its own row, hence the 9 number-tag differences and 3 identity-c failures.

### 10.5 Small contradictions and fraction-printed spreads

`contradicted_small` (ceiling `int_text_proposal_contradicted_small` 9, roles and codes; lists in 10.7):
- Blue Owl "SR+#" [256066]: "SR + 0.0725" read as a spread of 0.0725 percent; the tag is 7.25. The right reading is a
  spread printed as a fraction (times 100), a role the option list does not have. It is the only shape where a read
  number below 1 has a tag 100 times larger (`q_s9_fraction.sql`: 2 rows). The other read numbers below 1 (PIK parts of
  0.25 to 0.75, a 0.75 spread, two 0.95 coupons; `q_s9_fraction_all.sql`) have no such tag.
- Apollo "S+#, #% Floor" [8900b6] spread and floor (3 of 3 floor-identity rows fail); "#% Cash plus #% PIK, #% Floor"
  [b4ee19] cash and PIK (the all-in tag holds the cash part); "S+# Cash plus #% PIK, #% PIK" [8900b6] both PIK numbers
  (one cell prints two PIK rates); Apollo S=SOFR in two units (above).
Large populations with a few outliers stay out: Ares SOFR (54 outside of 10,076 tested) is needs_owner (weak_only).

Contradicted (ceiling `int_text_proposal_contradicted`, redefined over roles and codes: 6): the two BCRED SOFR codes
of the 2022 tables (base level, 2022 term SOFR), HPS B and C (dated legends, above), and the spread and floor roles of
Apollo "S+#, #% Floor" [b4ee19] (5 of 5 floor-identity rows fail: all-in tag holds the spread or floor). The ceiling
was 3 over shapes and codes; it is redefined, not loosened: under the old scope it would now read 5, the two new
codes being exposed by the four rate names.

### 10.6 Base level: what the check establishes

`separates_currency_bloc` (no rate of another currency admissible for more than 50% of the rows) is true only for the
prime rate (Ares "Base Rate" 17 of 17 quarters, BCRED P 3 of 3). For every other mapping some rate of another currency
passes: the monthly OECD proxies of NZD, AUD, NOK, KRW, SEK and CAD sit at the same levels as USD, GBP or EUR in many
quarters (`q_s9_bloc.sql`: Ares SOFR rows pass as BKBM in 14 of 17 quarters and as SONIA in 13; EURIBOR rows pass as
KORIBOR and STIBOR in every quarter). On the definition: STIBOR and KORIBOR are other currencies than EUR, so the
definition as briefed lets them block EUR; the EUR-against-USD separation shows only pairwise:

Pairwise (`review_r3_swap.sql`, run here): EURIBOR rows read as SOFR are 0 to 3% admissible from 2023-06-30 on (54% at
2023-03-31, 90 to 100% in 2022); SOFR rows read as EURIBOR 0 to 6% in every quarter (0 to 3% from 2022-12-31); PRIME
rows read as SOFR 0 to 4.5%; SOFR rows read as prime 0 to 0.5% from 2023-03-31 (28 to 37% in 2022). But SOFR rows pass
as fed funds (73 to 100%) and as the LIBOR proxy (98 to 100%) in every quarter, and as SONIA in 2024 to 2026 (59 to
100%); SONIA rows pass as SOFR in every quarter.

**What the check establishes:** the level of the currency bloc since mid-2023 (a USD loan is not read as EUR, nor the
reverse), and prime against everything else. **What it does not:** which dollar rate (SOFR, fed funds and the LIBOR proxy
cannot be told apart in any quarter), SOFR against SONIA from 2024, or any currency in 2022, when every series moved
together.

### 10.6b Tests and build (fix round 1)

Unit tests changed or added: the verdict rules (a two-number shape with the spread checked and the floor not:
partly_accepted; contradicted_small; leg evidence that does and does not count), the leg identities (sides,
independence, an all-printed row that cannot count), the base level (a CDOR proposal judged on the CORRA series), the
quarter (separates_currency_bloc). Baselines: `int_text_proposal_contradicted` 6 (redefined), new
`int_text_proposal_contradicted_small` 9, `int_text_leg_identity_fail` 18. Full build (`--threads 2`, log
`scratch/2026-11-26_text_slice_r2/full_build_fix1.log`): `PASS=1084 WARN=126 ERROR=0 TOTAL=1210`. pytests 180 passed. CI
fixture: step 4 `PASS=3`; build `PASS=677 WARN=5 ERROR=0 TOTAL=682`; empty run `PASS=2`; unit tests `PASS=70`.

### 10.7 Open proposals, full lists grouped by reason

Positions in brackets (for roles and shapes, the positions of the shape). `q_s9_open_lists.sql`.

- **code contradicted_small, Apollo** (2, 6372 positions): S=SOFR (3969); S=SOFR (2403)
- **code needs_owner / no_check_exists, Ares** (1, 2 positions): CAD Base Rate=Canadian base rate (CAD prime) (2)
- **code needs_owner / no_check_exists, BCRED** (4, 15 positions): CI=CIBOR (8); CI=CIBOR (5); CI=CIBOR (1); CI=CIBOR (1)
- **code needs_owner / no_check_exists, Blue Owl** (6, 5032 positions): SR=SOFR (3407); SR=SOFR (1343); L=LIBOR (208); L=LIBOR (70); P=PRIME (3); BB=BBSY (1)
- **code needs_owner / no_check_exists, Apollo** (3, 364 positions): SONIA=SONIA (208); SONIA=SONIA (153); N=NIBOR (3)
- **code needs_owner / no_check_exists, HPS** (2, 21 positions): SORA=SORA (13); BS=Bloomberg Short Term Bank Yield Index (8)
- **code needs_owner / role_not_a_rate, Apollo** (3, 7 positions): Equity plus=(not a code) (3); Variable=(not a code) (2); Equity plus=(not a code) (2)
- **code needs_owner / too_few_rows, Ares** (4, 56 positions): NIBOR=NIBOR (18); BBSY=BBSY (17); BKBM=BKBM (14); TONA=TONA (7)
- **code needs_owner / too_few_rows, BCRED** (17, 28 positions): B=BKBM (4); ST=STIBOR (2); ST=STIBOR (2); CA=CORRA (2); S=SONIA (2); P=PRIME (2); SA=SARON (2); P=PRIME (2); BB=BBSY (2); C=CDOR (1); E=EURIBOR (1); N=NIBOR (1); CA=CORRA (1); N=NIBOR (1); SORF=SOFR (1); B=BKBM (1); P=PRIME (1)
- **code needs_owner / too_few_rows, Blue Owl** (5, 59 positions): P=PRIME (26); SA=SONIA (25); B=BBSY (4); B=BBSY (3); B=BBSY (1)
- **code needs_owner / too_few_rows, Apollo** (6, 29 positions): SARON=SARON (12); K=KORIBOR (6); K=KORIBOR (4); T=TONA (3); SARON=SARON (3); NIBOR=NIBOR (1)
- **code needs_owner / too_few_rows, HPS** (1, 2 positions): BB=BKBM (2)
- **code needs_owner / weak_only, Ares** (6, 13202 positions): SOFR=SOFR (11359); LIBOR=LIBOR (1308); Euribor=EURIBOR (172); CORRA=CORRA (144); SONIA=SONIA (131); CDOR=CDOR (88)
- **code needs_owner / weak_only, BCRED** (1, 22 positions): S=SOFR (22)
- **code unstable, Blue Owl** (1, 17 positions): C=CORRA|CDOR (17)
- **code unstable, Apollo** (2, 5 positions): T=MUTKCALM|TONAR (4); N=(not a code)|NIBOR (1)
- **column needs_owner / below_bar, Ares** (1, 15233 positions): 1de53b4d55ea4050 all_in_rate (15233)
- **column needs_owner / no_check_exists, Ares** (1, 13657 positions): 9ecddf9faf035680 reference_rate_code (13657)
- **column needs_owner / no_check_exists, Blue Owl** (2, 3643 positions): 501a2d64caadc662 reference_rate_code (2109); aceeb6ccc5200e42 reference_rate_code (1534)
- **column unstable, Blue Owl** (1, 1416 positions): 0dd66cba8d2b8641 rate_terms (1416)
- **role contradicted_small, Blue Owl** (1, 2 positions): "SR+#" #1 spread_pct (2)
- **role contradicted_small, Apollo** (6, 4686 positions): "S+#, #% Floor" #1 spread_bps (2339); "S+#, #% Floor" #2 floor_pct (2339); "S+# Cash plus #% PIK, #% PIK" #2 pik_rate_pct (2); "S+# Cash plus #% PIK, #% PIK" #3 pik_rate_pct (2); "#% Cash plus #% PIK, #% Floor" #1 cash_rate_pct (2); "#% Cash plus #% PIK, #% Floor" #2 pik_rate_pct (2)
- **role needs_owner / no_check_exists, BCRED** (2, 2 positions): "#%.(incl. #% PIK)" #2 pik_rate_pct (1); "#%.(incl. #% PIK)" #2 pik_rate_pct (1)
- **role needs_owner / no_check_exists, Blue Owl** (4, 150 positions): "SR+#% (#% PIK)" #1 spread_pct (117); "S+#% (#% PIK)" #1 spread_pct (15); "E+#% (#% PIK)" #1 spread_pct (13); "L+#% (#% PIK)" #1 spread_pct (5)
- **role needs_owner / no_check_exists, Apollo** (61, 1299 positions): "E+#, #% Floor" #2 floor_pct (218); "SONIA+#, #% Floor" #2 floor_pct (201); "E+#, #% Floor" #2 floor_pct (169); "SONIA+#, #% Floor" #2 floor_pct (135); "L+#, #% Floor" #2 floor_pct (65); "S+# Cash plus #% PIK, #% Floor" #3 floor_pct (62); "S+# Cash plus #% PIK, #% Floor" #1 spread_bps (62); "S+# Cash plus #% PIK, #% Floor" #1 spread_bps (35); "S+# Cash plus #% PIK, #% Floor" #3 floor_pct (35); "C+#, #% Floor" #2 floor_pct (25); "P+#, #% Floor" #2 floor_pct (25); "P+#, #% Floor" #2 floor_pct (22); "SONIA+# Cash plus #% PIK, #% Floor" #3 floor_pct (18); "SONIA+# Cash plus #% PIK, #% Floor" #1 spread_bps (18); "BBSW+#, #% Floor" #2 floor_pct (17); "STIBOR+#, #% Floor" #2 floor_pct (10); "S+# (Includes #% PIK), #% Floor" #3 floor_pct (10); "BBSW+#, #% Floor" #2 floor_pct (10); "E+# Cash plus #% PIK, #% Floor" #3 floor_pct (10); "E+# Cash plus #% PIK, #% Floor" #1 spread_bps (10); "S+# (Includes #% PIK), #% Floor" #1 spread_bps (10); "STIBOR+#, #% Floor" #2 floor_pct (10); "S+# Cash (includes #% PIK)" #1 spread_bps (8); "S+# Cash plus #% PIK" #1 spread_bps (7); "K+#, #% Floor" #2 floor_pct (6); "C+#, #% Floor" #2 floor_pct (6); "SARON+#, #% Floor" #2 floor_pct (6); "SONIA+# Cash plus #% PIK, #% Floor" #1 spread_bps (5); "SONIA+# Cash plus #% PIK, #% Floor" #3 floor_pct (5); "T+#, #% Floor" #2 floor_pct (4); "E+# Cash plus #% PIK, #% Floor" #3 floor_pct (4); "BBSW+# Cash plus #% PIK, #% Floor" #1 spread_bps (4); "E+# Cash plus #% PIK, #% Floor" #1 spread_bps (4); "BBSW+# Cash plus #% PIK, #% Floor" #3 floor_pct (4); "K+#, #% Floor" #2 floor_pct (4); "E+# (Includes #% PIK)" #1 spread_bps (4); "Equity plus #% PIK, #% Floor" #1 pik_rate_pct (3); "SARON+# Cash plus #% PIK, #% Floor" #1 spread_bps (3); "L+# Cash plus #% PIK" #1 spread_bps (3); "SARON+# Cash plus #% PIK, #% Floor" #3 floor_pct (3); "SARON+# (Includes #% PIK)" #1 spread_bps (3); "T+#, #% Floor" #2 floor_pct (3); "SARON+#, #% Floor" #2 floor_pct (3); "N+#, #% Floor" #2 floor_pct (3); "Equity plus #% PIK, #% Floor" #2 floor_pct (3); "E+# Cash plus #% PIK" #1 spread_bps (2); "SONIA+# (Includes #% PIK)" #1 spread_bps (2); "Equity plus #% PIK" #1 pik_rate_pct (2); "STIBOR+# Cash plus #% PIK, #% Floor" #1 spread_bps (2); "#% Cash plus #% PIK, #% Floor" #3 floor_pct (2); "STIBOR+# Cash plus #% PIK, #% Floor" #3 floor_pct (2); "S+# Cash plus #% PIK, #% PIK" #1 spread_bps (2); "STIBOR+# (Inlcudes #% PIK)" #1 spread_bps (2); "BBSW+# Cash plus #% PIK, #% Floor" #1 spread_bps (1); "N+#, #% Floor" #2 floor_pct (1); "S+# Cash plus #% PIK, # Floor" #3 floor_pct (1); "NIBOR+#, #% Floor" #2 floor_pct (1); "BBSW+# Cash plus #% PIK, #% Floor" #3 floor_pct (1); "#% (includes #% PIK), #% Floor" #3 floor_pct (1); "L+# Cash (includes #% PIK)" #1 spread_bps (1); "S+# Cash plus #% PIK, # Floor" #1 spread_bps (1)
- **role needs_owner / role_not_a_rate, Blue Owl** (2, 5730 positions): "#%" #1 pct_of_net_assets (4333); "#%" #1 pct_of_net_assets (1397)
- **role needs_owner / too_few_rows, Ares** (3, 4 positions): "#%PIK" #1 pik_rate_pct (2); "#% (#%PIK)" #1 all_in_rate_pct (1); "#% (#%PIK)" #2 pik_rate_pct (1)
- **role needs_owner / too_few_rows, BCRED** (35, 57 positions): "#% (incl. #% PIK)" #2 pik_rate_pct (4); "#% (incl. #% PIK)" #1 all_in_rate_pct (4); "B+#%" #1 spread_pct (4); "BB+#%" #1 spread_pct (2); "#% PIK" #1 pik_rate_pct (2); "S+#%" #1 spread_pct (2); "#%" #1 pik_rate_pct (2); "ST+#%" #1 spread_pct (2); "# (incl. #% PIK)" #2 pik_rate_pct (2); "P+#%" #1 spread_pct (2); "ST+#%" #1 spread_pct (2); "# (incl. #% PIK)" #1 all_in_rate_pct (2); "SA+#%" #1 spread_pct (2); "P+#%" #1 spread_pct (2); "L+#% PIK" #1 pik_spread_pct (2); "CA+#%" #1 spread_pct (2); "L+#% (incl. #% PIK)" #1 spread_pct (1); "L+#% (incl. #% PIK)" #1 spread_pct (1); "B+#%" #1 spread_pct (1); "CI+#%" #1 spread_pct (1); "L+#% PIK" #1 pik_spread_pct (1); "E+#%" #1 spread_pct (1); "N+#%" #1 spread_pct (1); "CI+#%" #1 spread_pct (1); "SORF+#%" #1 spread_pct (1); "CA+#%" #1 spread_pct (1); "#%.(incl. #% PIK)" #1 all_in_rate_pct (1); "L+#% (incl. #% PIK)" #2 pik_rate_pct (1); "N+#%" #1 spread_pct (1); "P+#%" #1 spread_pct (1); "#%.(incl. #% PIK)" #1 all_in_rate_pct (1); "L+#% (incl. #% PIK)" #2 pik_rate_pct (1); "C+#%" #1 spread_pct (1); "#% PIK" #1 pik_rate_pct (1); "#% PIK" #1 pik_rate_pct (1)
- **role needs_owner / too_few_rows, Blue Owl** (4, 6 positions): "P+#%" #1 spread_pct (3); "BB+#%" #1 spread_pct (1); "B+#%" #1 spread_pct (1); "#" #1 spread_pct (1)
- **role needs_owner / too_few_rows, Apollo** (27, 93 positions): "S+# (includes #% PIK)" #1 spread_bps (28); "#% (includes #% PIK)" #1 all_in_rate_pct (6); "P+#" #1 spread_bps (4); "T+#, #% Floor" #1 spread_bps (4); "E+# Cash plus #% PIK, #% Floor" #2 pik_rate_pct (4); "E+# (Includes #% PIK)" #2 pik_rate_pct (4); "K+#, #% Floor" #1 spread_bps (4); "BBSW+# Cash plus #% PIK, #% Floor" #2 pik_rate_pct (4); "SARON+#, #% Floor" #1 spread_bps (3); "T+#, #% Floor" #1 spread_bps (3); "N+#, #% Floor" #1 spread_bps (3); "L+# Cash plus #% PIK" #2 pik_rate_pct (3); "SARON+# (Includes #% PIK)" #2 pik_rate_pct (3); "SARON+# Cash plus #% PIK, #% Floor" #2 pik_rate_pct (3); "STIBOR+# (Inlcudes #% PIK)" #2 pik_rate_pct (2); "STIBOR+# Cash plus #% PIK, #% Floor" #2 pik_rate_pct (2); "E+# Cash plus #% PIK" #2 pik_rate_pct (2); "SONIA+# (Includes #% PIK)" #2 pik_rate_pct (2); "BBSW+# Cash plus #% PIK, #% Floor" #2 pik_rate_pct (1); "L+# Cash (includes #% PIK)" #2 pik_rate_pct (1); "N+#, #% Floor" #1 spread_bps (1); "NIBOR+#, #% Floor" #1 spread_bps (1); "#% Cash plus #% PIK" #2 pik_rate_pct (1); "#% Cash plus #% PIK" #1 cash_rate_pct (1); "S+# Cash plus #% PIK, # Floor" #2 pik_rate_pct (1); "#% (includes #% PIK), #% Floor" #1 all_in_rate_pct (1); "#% (includes #% PIK), #% Floor" #2 pik_rate_pct (1)
- **role needs_owner / too_few_rows, HPS** (12, 28 positions): "#% (incl #% PIK)" #1 all_in_rate_pct (4); "#% (incl #% PIK)" #2 pik_rate_pct (4); "B+#% (incl #% PIK)" #1 spread_pct (2); "SF+#% (incl. #% PIK)" #1 spread_pct (2); "BB+#%" #1 spread_pct (2); "L+#% PIK" #1 pik_spread_pct (2); "SF+#% (incl #%PIK)" #1 spread_pct (2); "P+#% (incl #% PIK)" #1 spread_pct (2); "B+#% (incl #% PIK)" #2 pik_rate_pct (2); "SF+#% (incl. #% PIK)" #2 pik_rate_pct (2); "SF+#% (incl #%PIK)" #2 pik_rate_pct (2); "P+#% (incl #% PIK)" #2 pik_rate_pct (2)
- **role unstable, BCRED** (2, 47 positions): "#%" #1 fixed_rate_pct (34); "#%" #1 fixed_rate_pct (13)
- **role unstable, Blue Owl** (4, 52 positions): "#%" #1 fixed_rate_pct (19); "(em dash)%" #1 other_number (19); "#% (#% PIK)" #1 cash_rate_pct (7); "#% (#% PIK)" #2 pik_rate_pct (7)
- **role unstable, Apollo** (4, 10 positions): "S+# PIK" #1 pik_spread_pct (4); "#% Cash plus #% PIK, #% Floor" #2 pik_rate_pct (2); "#% Cash plus #% PIK, #% Floor" #3 floor_pct (2); "#% Cash plus #% PIK, #% Floor" #1 all_in_rate_pct (2)
- **shape contradicted_small, Blue Owl** (1, 2 positions): "SR+#" (2)
- **shape contradicted_small, Apollo** (3, 2343 positions): "S+#, #% Floor" (2339); "S+# Cash plus #% PIK, #% PIK" (2); "#% Cash plus #% PIK, #% Floor" (2)
- **shape needs_owner, Ares** (2, 3 positions): "#%PIK" (2); "#% (#%PIK)" (1)
- **shape needs_owner, BCRED** (31, 49 positions): "#% (incl. #% PIK)" (4); "B+#%" (4); "#% PIK" (2); "ST+#%" (2); "#%" (2); "CA+#%" (2); "SA+#%" (2); "P+#%" (2); "# (incl. #% PIK)" (2); "ST+#%" (2); "P+#%" (2); "L+#% PIK" (2); "S+#%" (2); "BB+#%" (2); "C+#%" (1); "#% PIK" (1); "CI+#%" (1); "L+#% (incl. #% PIK)" (1); "E+#%" (1); "#% PIK" (1); "#%.(incl. #% PIK)" (1); "CA+#%" (1); "CI+#%" (1); "L+#% PIK" (1); "N+#%" (1); "L+#% (incl. #% PIK)" (1); "P+#%" (1); "N+#%" (1); "SORF+#%" (1); "B+#%" (1); "#%.(incl. #% PIK)" (1)
- **shape needs_owner, Blue Owl** (6, 5736 positions): "#%" (4333); "#%" (1397); "P+#%" (3); "B+#%" (1); "#" (1); "BB+#%" (1)
- **shape needs_owner, Apollo** (25, 62 positions): "P+#" (4); "E+# (Includes #% PIK)" (4); "BBSW+# Cash plus #% PIK, #% Floor" (4); "K+#, #% Floor" (4); "T+#, #% Floor" (4); "E+# Cash plus #% PIK, #% Floor" (4); "Equity plus #% PIK, #% Floor" (3); "SARON+# Cash plus #% PIK, #% Floor" (3); "SARON+# (Includes #% PIK)" (3); "SARON+#, #% Floor" (3); "T+#, #% Floor" (3); "N+#, #% Floor" (3); "L+# Cash plus #% PIK" (3); "Equity plus #% PIK" (2); "E+# Cash plus #% PIK" (2); "STIBOR+# Cash plus #% PIK, #% Floor" (2); "SONIA+# (Includes #% PIK)" (2); "STIBOR+# (Inlcudes #% PIK)" (2); "#% Cash plus #% PIK" (1); "NIBOR+#, #% Floor" (1); "L+# Cash (includes #% PIK)" (1); "BBSW+# Cash plus #% PIK, #% Floor" (1); "S+# Cash plus #% PIK, # Floor" (1); "#% (includes #% PIK), #% Floor" (1); "N+#, #% Floor" (1)
- **shape needs_owner, HPS** (7, 16 positions): "#% (incl #% PIK)" (4); "B+#% (incl #% PIK)" (2); "SF+#% (incl. #% PIK)" (2); "L+#% PIK" (2); "P+#% (incl #% PIK)" (2); "BB+#%" (2); "SF+#% (incl #%PIK)" (2)
- **shape partly_accepted, Blue Owl** (4, 150 positions): "SR+#% (#% PIK)" (117); "S+#% (#% PIK)" (15); "E+#% (#% PIK)" (13); "L+#% (#% PIK)" (5)
- **shape partly_accepted, Apollo** (25, 1114 positions): "E+#, #% Floor" (218); "SONIA+#, #% Floor" (201); "E+#, #% Floor" (169); "SONIA+#, #% Floor" (135); "L+#, #% Floor" (65); "S+# Cash plus #% PIK, #% Floor" (62); "S+# Cash plus #% PIK, #% Floor" (35); "S+# (includes #% PIK)" (28); "C+#, #% Floor" (25); "P+#, #% Floor" (25); "P+#, #% Floor" (22); "SONIA+# Cash plus #% PIK, #% Floor" (18); "BBSW+#, #% Floor" (17); "E+# Cash plus #% PIK, #% Floor" (10); "STIBOR+#, #% Floor" (10); "STIBOR+#, #% Floor" (10); "BBSW+#, #% Floor" (10); "S+# (Includes #% PIK), #% Floor" (10); "S+# Cash (includes #% PIK)" (8); "S+# Cash plus #% PIK" (7); "SARON+#, #% Floor" (6); "K+#, #% Floor" (6); "#% (includes #% PIK)" (6); "C+#, #% Floor" (6); "SONIA+# Cash plus #% PIK, #% Floor" (5)
- **shape unstable, BCRED** (2, 47 positions): "#%" (34); "#%" (13)
- **shape unstable, Blue Owl** (3, 45 positions): "(em dash)%" (19); "#%" (19); "#% (#% PIK)" (7)
- **shape unstable, Apollo** (2, 6 positions): "S+# PIK" (4); "#% Cash plus #% PIK, #% Floor" (2)
