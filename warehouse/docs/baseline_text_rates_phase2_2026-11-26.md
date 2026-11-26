# Baseline: rate text, slice R phase 2 (2026-11-26)

Branch `warehouse-text-spec`. Builds on `baseline_text_rates_phase1_2026-11-26.md` (sections 12 to 14) and the agent
run `baseline_text_rates_agent_run_2026-11-26.md` (run of record `text_runs/2026-11-26_rates_run3`). Queries:
`scripts/text/q_s0_*.sql` to `q_s6_*.sql`. No model call, no network.

**Proposals only, nothing published.** The agent's rules are loaded as seeds and read into proposal models that no
spine, staging or mart model reads; no rule was written to a wrapper. **No page was read by a person.** Passing a check
means the proposal is consistent with the filer's tags, its footnote legend and public rate series. It does not mean a
value is correct.

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
no_value 1,615 ("N/A" and the like); number_not_parsed 0; role_cannot_tell 0.

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

- Ares "#% (#% PIK)" 13: the PIK part printed in brackets (e.g. "10.35% (3.00% PIK)") against a PIK tag of another value
  (9.57 on the example row); Ares "#% PIK" 1 ("19.00% PIK" against 12.29). Ares spread "#%" 3 and all-in "#%" 2: one
  value printed, another tagged (6.00 / 5.75).
- BCRED all-in "#%" 9: printed coupon differs from the tag (e.g. 5.84 printed against 8.63 tagged; 2022-09-30).
- Blue Owl "SR+#% (#% PIK)" 6: the PIK tag equals the spread (5.75), not the printed PIK part (2.50). Blue Owl "SR+#" 2:
  the cell prints "SR + 0.0725", a fraction; the tag is 7.25 (the proposal reads 0.0725 as a percent).
- Apollo fixed "#%" 4: tag 0.07 against "10.36%" (a tag in a fraction-scale left unconverted). Apollo "S+#, #% Floor" 2:
  "S+385" against a spread tag 0.38 (tag scale). Apollo "#% Cash plus #% PIK, #% Floor" 2 and "#% Cash plus #% PIK" 1:
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
  sits 3 points above every other rate.
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
- Baselines (measured): `int_text_rate_proposed_number_not_parsed` 0, `int_text_proposal_contradicted` 3,
  `int_text_leg_identity_fail` 18.
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
   discriminates it in every quarter.
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
