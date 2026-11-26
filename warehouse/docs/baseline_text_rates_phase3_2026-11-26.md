# Baseline: rate text, slice R phase 3, the accepted rules applied (2026-11-26)

Branch `warehouse-text-spec`. Builds on `baseline_text_rates_phase2_2026-11-26.md` (section 10) and the owner's answers
in `owner_review_text_rates_2026-11-26.md` (last section), plus the owner's two additions of 2026-11-26 (A: constraints
on the read model; B: a reference-rate table). Queries: `scripts/text/q_t3_*.sql`. No model call, no network.

**Nothing is published.** The read model publishes nowhere outside the warehouse (no spine, cmp or mart model reads it;
pytest `test_text_models_no_production.py`). **No page was read by a person.** A rule graded `checked` agrees with the
filer's own tags or legend; that is consistency, not correctness: on nearly every compared row the tag sits in the cell
being read. **Agreement with production is not correctness.** "No finding" from a constraint does not detect a field
whose meaning changed, a wrong rate on the right row, or offsetting errors.

Funds: Ares (0001287750), BCRED (0001803498), Blue Owl (0001812554), Apollo (0001837532), HPS (0001838126).

## 1. What was built

| Object | What it does |
|---|---|
| `int_text_rate_proposed` (changed) | Proposals match a cell's shape by exact spelling, not upper case (check fix 1b) |
| `int_text_check_leg_arithmetic` (changed) | Identity d is `not_testable` where the all-in TAG equals the margin or the floor alone (fix 1a) |
| `int_text_check_base_level` (changed) | Input state `all_in_tag_is_leg`, same mechanism; verdict moved into macro `base_level_verdict` |
| `int_text_check_code_legend` (comment) | Stale line 10 corrected (fix 1c) |
| `int_text_check_fixed_rate` (new) | Owner item 11 check (fix 1d) |
| `int_text_proposal_verdict` (changed) | Evidence per spelling; not_testable leg rows count neither way; fixed-rate relabel; column `label_changed_by` |
| seeds `reference_rate`, `reference_rate_name` (new) | Owner addition B: one row per benchmark; printed legend names to rates. Exact lookup, no substring |
| `int_text_legend_rate` (new) | Per filing and code: the rates the filing's own legend gives (one_rate, two_rates, unresolved) |
| `scripts/text/accepted_rules_to_wrappers.py` (new) | Writes the accepted rules into the five wrapper copies (`reading_rules`, target `rate_text`), deterministic, `--check` mode |
| readings loader version 8 | A `reading_rules` parameter may be an object, stored as canonical JSON; existing rule ids unchanged |
| seed `reading_action` | Five actions, target `rate_text`: `rate_column`, `rate_role`, `rate_code`, `rate_text_not_a_code`, `rate_printed_wins` |
| `int_text_rate_rule` (new) | The rules, typed, with `source_grade` |
| `int_text_rate_read_cell` (new) | Every printed rate cell in a ruled column read with the rules, status per number and code |
| `int_text_rate_read` (new) | Per position: reference rate, spread, floor, all-in, cash, PIK, PIK spread, rate type, each with rule id, grade, status. Constraints A1 to A3 applied |
| `int_text_rate_constraint` (new) | Constraints A4 (legs) and A5 (base level, through `base_level_verdict`) |

Wrapper rules: the extension is one loader change (object parameters) and five seed actions; the grade lives in the
parameter (`source_grade`). Generated rule counts:

| Fund | rate_column | rate_role | rate_code | other |
|---|---|---|---|---|
| Ares | checked 1, owner 2 | checked 5, matches_few_rows 3 | owner 2 (Base Rate, CAD Base Rate) | - |
| BCRED | checked 14 | checked 69, matches_few_rows 34, untested 2 | checked 12, owner 1 | printed_wins 1 |
| Blue Owl | checked 5, owner 3 | checked 23, matches_few_rows 4, untested 1 | checked 5, owner 3 | - |
| Apollo | checked 2 | checked 31, matches_few_rows 23, untested 54 | checked 7, owner 3 | not_a_code 2 |
| HPS | checked 2 | checked 36, matches_few_rows 12 | checked 8, owner 7 | - |

Item 1 (a code that is a rate's own name) is the general rule of seed `reference_rate`, not a wrapper entry; its
readings cite rule id `reference_rate:<rate>`, grade owner.

## 2. Check fixes and every proposal whose verdict or label changed (`q_t3_verdict_changes.sql`)

| Fix | Mechanism |
|---|---|
| 1a | A floating loan's all-in rate is a base rate above zero plus its margin. An all-in TAG equal to the margin or the printed floor alone holds another leg; identity d and the base level cannot test it (`not_testable` / `all_in_tag_is_leg`). Applies to any fund; Apollo's 8 rows are the only ones today. A printed all-in equal to the spread still fails d (unit test p16) |
| 1b | A proposal applies only to the spelling the agent saw; another spelling of the same upper-case shape is `no_proposal` and contributes no evidence |
| 1d | Per single-number, code-free shape where some order says spread or fixed: on positions with no code read in any column and an all-in tag, the number equals the tag on at least 5 rows and 90% -> role `fixed_rate_pct`, accepted by check `fixed_rate_no_code`. The check settles a fixed/spread split between orders |

| Proposal | Before | After | Why |
|---|---|---|---|
| Apollo code S=SOFR [8900b6] (2,403 pos.) | contradicted_small | accepted_by_check (legend) | 1a: its base-level rows had all-in tags holding the spread or floor |
| Apollo code S=SOFR [b4ee19] (3,969) | contradicted_small | accepted_by_check (legend) | same |
| Apollo "S+#, #% Floor" [b4ee19] spread (3,875) | contradicted | accepted_by_check (number_tag 3,858 of 3,859) | 1a |
| Apollo "S+#, #% Floor" [b4ee19] floor | contradicted | needs_owner (no check exists) | 1a; read as untested under item 5 |
| Apollo "S+#, #% Floor" [8900b6] spread (2,339) | contradicted_small | accepted_by_check (2,337 of 2,338) | 1a |
| Apollo "S+#, #% Floor" [8900b6] floor | contradicted_small | needs_owner | 1a |
| the two shapes above | contradicted / contradicted_small | partly_accepted | spread accepted, floor not checkable |
| BCRED "#%" [16de07] (13) | unstable (fixed / spread) | fixed_rate_pct, accepted (6 of 6) | 1d, label changed |
| BCRED "#%" [35d86f] (34) | unstable (fixed / spread) | fixed_rate_pct, accepted (20 of 20) | 1d, label changed |
| Apollo "S+# (includes #% PIK)" [b4ee19] | 28 positions, PIK 27 compared | 15 positions, PIK 15 of 15 | 1b; "S+# (Includes #% PIK)" (13) now unread |
| Apollo "E+# (Includes #% PIK)", "SARON+# (Includes #% PIK)" | 4 and 3 positions | 3 and 2 | 1b |
| Ares "Base Rate (M)", "Base Rate (Q)", "Euribor (Q)" (nothing_to_read) | 18, 376, 101 positions | 17, 330, 99 | 1b: case variants counted apart |

Fixed-rate check, every shape in scope (`q_t3_fixed_check.sql`): fixed_rate on BCRED [4911ba] 141/141, [d30801]
217/217, [fc9493] 16/16, [35d86f] 20/20, [16de07] 6/6; Apollo [8900b6] 143/146, [b4ee19] 150/151; HPS [836097] 60/60.
Only [16de07] and [35d86f] change label: the others were already proposed as fixed rates in both orders. HPS [836097]
was proposed fixed in both orders in this build, so the owner's note that HPS was accepted as "spread" does not match
this build's verdicts; no HPS label changed. BCRED [7bedc6] "#%" (5 rows, 4 compared, 4 equal): too_few_rows, stays a
spread proposal; constraint A1 then drops its 5 spreads (section 5). Blue Owl [256066] "#%" (19): no all-in tag, no
check; read as fixed rate, grade untested (owner item 11). Ares [4f40f4] and Blue Owl [010c64], [0429e1]: their rows
carry a code in another column, so they are not compared (false-positive guard; unit test
`int_text_check_fixed_rate_false_positive`).

Baselines lowered, no row hidden: contradicted 6 -> 4, contradicted_small 9 -> 5, leg identity fail 18 -> 10 (the 8 d
rows are not_testable).

## 3. Positions read, per fund and field (`q_t3_read_summary.sql`, all positions; published in brackets)

Read = status read_equals_tag, read_no_tag or printed_wins_over_tag. Grades: c checked, m matches_few_rows, o owner,
u untested.

| Fund | Reference rate | Spread | Floor | All-in (incl. fixed) | PIK rate | PIK spread |
|---|---|---|---|---|---|---|
| Ares | o 13,657 | c 13,654, m 0 | - | c 13,686, m 1 | c 2,790, m 3 | - |
| BCRED | c 22,628, o 15 | c 22,609, m 31 | - | c 23,340, m 8 | c 1,097, m 11, u 2 | m 3 |
| Blue Owl | c 3,620, o 5,036 | c 8,249, m 5 | - | u 19 | c 646 | c 120 |
| Apollo | c 6,987, o 393 | c 7,137, m 18, u 30 | u 7,308 | c 320, m 1 | c 238, m 31, u 5 | - |
| HPS | c 6,329, o 153 | c 6,284, m 10 | - | c 6,564, m 4 | c 683, m 12 | c 186, m 2 |

Not read although printed (positions): differs_from_tag Ares all-in 2, PIK 14, spread 3; Blue Owl PIK 6; Apollo all-in
4, spread 2 (the tag first; listed by the read model). Constraint drops in section 5. Cash rate: read nowhere (the
"Cash plus PIK" shapes are unstable or contradicted; no accepted rule reads a cash leg). Rate type: fixed Ares 0, BCRED
478, Blue Owl 19, Apollo 320, HPS 73; floating Ares 13,654, BCRED 22,643, Blue Owl 8,374, Apollo 7,185, HPS 6,482.

BCRED's printed_wins rule: 9 positions (rows 826 to 834) keep the printed all-in rate over the shifted tag; row 835
has no tag (read_no_tag).

## 4. Unread cells (`tests/baseline_int_text_rate_unread.sql`, 41 groups; `q_t3_unread_and_dropped.sql`)

| Fund | Shape (example) | Status | Positions |
|---|---|---|---|
| BCRED | S+#% ("S + 5.25%", 2022-12-31) | legend_two_rates | 12 |
| BCRED | S+#% (2022-09-30) | code_no_rule (not carried across the 2022-12-31 two-name legend) | 10 |
| BCRED | #% | no_role_rule | 2 |
| BCRED | SORF+#% | code_no_rule | 1 |
| Blue Owl | SR+#% (#% PIK), S+#% (#% PIK), E+#% (#% PIK), L+#% (#% PIK) | no_role_rule (spread role never compared; PIK part read) | 117, 15, 13, 5 |
| Blue Owl | #% (#% PIK) | no_role_rule (unstable) | 7 |
| Blue Owl | C+#% (before 2024-12-31) | code_no_rule (not carried across a two-name legend) | 15 |
| Blue Owl | C+#% (2024-12-31) | legend_two_rates | 2 |
| Blue Owl | SR+# ("SR + 0.0725", item 12) | no_role_rule | 2 |
| Blue Owl | BB+#% | code_no_rule | 1 |
| Apollo | S+# Cash plus #% PIK, #% Floor; SONIA+...; E+...; S+# Cash plus #% PIK; S+# Cash (includes #% PIK) | no_role_rule (spread no check, shape 5+ positions) | 97, 23, 10, 7, 8 |
| Apollo | S+# (Includes #% PIK) (case variant), S+# (Includes #% PIK), #% Floor | no_role_rule | 13, 10 |
| Apollo | S+# (includes #% PIK) spread | no_role_rule (PIK part read) | 15 |
| Apollo | #% (includes #% PIK); S+# PIK; #% Cash plus #% PIK, #% Floor; S+# Cash plus #% PIK, #% PIK; and 5 one-position shapes | no_role_rule | 6, 4, 4, 2, 5 |
| Apollo | N+#, #% Floor | code_no_rule (item 4: N unread) | 4 |
| Apollo | NIBOR+#, #% Floor | legend_two_rates (the legend names NOWA and abbreviates NIBOR) | 1 |
| Apollo | Equity plus ...; Variable | not_a_code (item 13) | 5, 2 |
| HPS | C+#% (2025-06-30 to 2025-12-31), B+#% (2024-12-31) | legend_two_rates (item 3: transition filings) | 10, 8 |

A shape that is not accepted stays unread even where part of it is read (the PIK part of Blue Owl's "(#% PIK)" shapes,
the floor of Apollo's "Cash plus PIK, Floor" shapes).

## 5. Constraints 1 to 3: readings not applied (`tests/baseline_int_text_rate_constraint_dropped.sql`, 102)

| Fund | Field | Constraint / detail | Positions | Example | Rules |
|---|---|---|---:|---|---|
| Ares | spread | A1, no code | 1 | "8.00%" | 1 spread rule |
| BCRED | spread | A1, code printed but unread | 23 | "S + 2.19%" (2022 S codes) | 2 |
| BCRED | spread | A1, no code | 5 | "6.75%" ([7bedc6] "#%", too few rows for the fixed check) | 1 |
| Blue Owl | spread | A1, no code | 21 | "10.00%" in the "Cash" column (fixed coupons) | 2 |
| Blue Owl | spread | A1, code printed but unread | 18 | "BB + 5.75%", "C + 4.50%" | 2 |
| Apollo | floor | A2 | 11 | "12.50% (includes 6.25% PIK), 1.00% Floor"; "Equity plus" rows | 6 |
| Apollo | spread | A1, code printed but unread | 5 | "N+475, 0.00% Floor" | 3 |
| HPS | spread | A1, code printed but unread | 18 | "B + 4.75%", "C + 4.50%" (transition legends) | 2 |

A3 (fixed rate beside floating terms): 0 positions. No rule was relabelled by a constraint; the readings were dropped
and listed. The 21 Blue Owl "10.00%" spreads and BCRED's 5 are the general form of item 11: numbers with no reference
rate, not spreads; no rule reads them as fixed rates (Blue Owl's "Cash" column has no all-in tag to check them).

## 6. Constraints 4 and 5 (`int_text_rate_constraint`; `q_t3_constraints.sql`)

A4 (all-in = cash + PIK): 0 rows; no position reads a cash rate. A5 (implied base inside the window of its rate):

| Fund | Tested (pass + fail) | Fail | Fail by rate | Not testable |
|---|---:|---:|---|---|
| Ares | 11,784 | 86 | SOFR 54, LIBOR 20, SONIA 5, CDOR 4, BBSY 3 | PIK leg 1,482; Base Rate and CAD Base Rate no series 369; EURIBOR window empty 21; no spread 1 |
| BCRED | 21,548 | 202 | SOFR 138, LIBOR 41, PRIME 6, CDOR 5, EURIBOR 4, SARON 4, SONIA 2, BKBM 1, STIBOR 1 | PIK 1,022; CIBOR 15; EURIBOR window empty 58 |
| Blue Owl | 0 | 0 | - | no all-in rate printed or tagged 8,088; PIK 566; no spread 2 |
| Apollo | 0 | 0 | - | no all-in 7,142; PIK 228; all-in tag equal to the spread or floor 5 (fix 1a); no spread 5 |
| HPS | 5,666 | 18 | SOFR 15, BBSW 2, SONIA 1 | PIK 717; BSBY and SORA no series 15; no all-in 54; EURIBOR window empty 30 |

By year (`review_p3_r2_c5.sql`, after fix round 1): 168 of the 306 failures are in 2022 (Ares 67, BCRED 101), where
term SOFR ran above overnight SOFR during the hikes (phase 2 section 4.3) and every series moved together. The 64 SOFR
failures in 2024 to 2026 (Ares 11, BCRED 41, HPS 12) are not explained; they were not traced row by row. The test lists
every failing row with its rules.

## 7. Comparison with production (published positions both sides hold; `q_t3_vs_production.sql`, `_detail.sql`, `q_t3_production_only.sql`, `q_t3_fixed_vs_production.sql`)

Regenerated from the database after fix round 1 (`scratch/2026-11-26_text_slice_r3/fix1/q_t3_vs_production.tsv`); the
first version of this table did not reproduce (BCRED reference rate and spread, Blue Owl reference rate and spread).

| Fund | Field | Same | Differ | New only | Production only |
|---|---|---:|---:|---:|---:|
| Ares | reference rate | 12,383 | 3 | 379 | 0 |
| Ares | spread / all-in / PIK | 12,759 / 13,080 / 2,603 | 0 / 0 / 0 | 3 / 1,148 / 1 | 4 / 2 / 24 |
| BCRED | reference rate / spread / all-in / PIK | 13,874 / 13,894 / 14,380 / 923 | 0 / 0 / 9 / 0 | 0 / 0 / 3 / 0 | 22 / 13 / 3 / 3 |
| Blue Owl | reference rate / spread / all-in / PIK | 6,830 / 6,331 / 36 / 591 | 4 / 138 / 0 / 0 | 0 / 0 / 1 / 0 | 18 / 350 / 70 / 135 |
| Apollo | reference rate / spread / all-in / PIK | 6,660 / 6,493 / 277 / 241 | 15 / 14 / 0 / 0 | 0 | 4 / 172 / 69 / 30 |
| HPS | reference rate / spread / all-in / PIK | 6,384 / 6,224 / 6,480 / 695 | 10 / 0 / 0 / 0 | 0 | 18 / 190 / 62 / 188 |

Ares all-in new only 1,148 (fix round 1): whole-coupon PIK readings ("10.00% PIK" in "Coupon", owner item 9) on rows
where production holds no rate. Phase 4 measured 838 Ares PIK-only rows of preferred stock, common equity or a fund
(production: no rate); these are likely the same rows, not checked row by row. Whether a PIK dividend on preferred
stock is an "all-in rate" is a class question (slice C), open for the owner.

Causes, every class of difference:

| Class | Positions | Cause |
|---|---:|---|
| Apollo K -> KORIBOR, T -> TONA, production SOFR | 9 + 6 | Production's known error (Apollo K/T/N held as SOFR). Apollo N stays unread here (item 4) |
| HPS BS -> BSBY, BB -> BKBM, production SOFR or LIBOR | 8 + 2 | Production's known error (HPS BS/BB) |
| Ares "Base Rate" stored, production empty | 379 | Item 13: stored as printed, no benchmark; production holds no reference rate |
| Ares "CAD Base Rate" (production SOFR) 2, "Euribor (M)" (production SOFR) 1 | 3 | The cell prints the name; production's value is its guess (not traced) |
| Blue Owl SR -> SOFR, production LIBOR | 4 | Not traced; the SR=SOFR rule is carried from the fund's one 2024-12-31 legend (item 2) |
| BCRED all-in, printed_wins rule | 9 | Production holds the shifted tag (the neighbour's rate); here the printed rate (owner, BCRED 2022-09-30) |
| Blue Owl spread 138, Apollo spread 14 | 152 | Production's spread equals this layer's spread plus the PIK number, on all 152 (`review_p3_r2_spread_diff.sql`). That PIK number is read here as `pik_rate`, not `pik_spread`: Blue Owl's "PIK" column cells ("#%") and Apollo's "... Cash plus #% PIK" carry the role pik_rate_pct. The spread tag is absent on all 152. Production sums them by its `cash_plus_pik` reading. Open owner questions: does "spread" include the PIK margin; is a PIK margin printed beside a reference rate a PIK spread or a PIK rate. No label changed without evidence |
| Apollo "Cash plus PIK" read two ways | - | Those shapes ("#% Cash plus #% PIK" 1, "...Floor" 4) stay unread here (unstable); production's two readings are not reproduced |
| Production fixed rates also held as a spread | BCRED 11, HPS 6 | Rules read them as fixed rates (rate type fixed, no spread); production holds the same number as basis_spread too (HPS 6 also coupon type floating). Production holds the other 361 + 67 + 19 + 276 fixed rates with no spread |
| Rate type floating, production empty | Blue Owl 122, HPS 89, Ares 4 | Code plus PIK spread ("E + 7.00% PIK"): floating here; production sets no coupon type |
| Rate type, other | Ares 3 (floating vs fixed), HPS 4 (floating vs fixed), Apollo 1 (fixed vs empty) | Not traced |
| Production only: all-in where this layer reads only a PIK rate | Blue Owl 70, Apollo 53, HPS 62, BCRED 3 (Ares 0 since fix round 1: whole coupon) | PIK-only coupons ("10.50% PIK"): production reads the coupon as the rate (phase 4 `printed_rate_type_and_loan_class_not_read`); no accepted rule says a PIK-only number is the all-in rate |
| Production only: PIK where this layer reads a PIK spread | HPS 115, Blue Owl 120, BCRED 2 | Same number, labelled PIK spread here ("SF + 7.75% PIK") and PIK rate in production |
| Production only: spread where this layer reads a PIK spread | HPS 184, Blue Owl 107, BCRED 2 | Production reads the PIK margin as the spread (its `margin_from_pik`) |
| Production only: dropped by constraint 1 | 1 | Section 5 and fix round 1 (was 64) |
| Production only: reference rate | 62 | Codes left unread here, status code_undecided (two-name legends, not carried, item 4 letters) |
| Production only: other | Blue Owl spread 243, Apollo spread 170, Apollo PIK 30, HPS PIK 73, others under 20 | Mostly shapes whose spread role was not accepted (section 4); not traced row by row |

## 8. Rates this layer leaves unread that production holds (`q_t3_unread_now_read.sql`)

The figure 1,772 (text_fields.md, 2026-11-25) cannot be traced to any query. This section uses `cmp_rate`: 1,552 rows
(1,407 distinct positions) with outcome new_empty on interest_rate, cash leg, PIK rate and spread, both bases. Numbers
after fix round 1:

| Field | Unread | Now read | Equal to production | Differ |
|---|---:|---:|---:|---:|
| interest_rate | 606 | 416 | 416 | 0 |
| interest_rate_cash | 145 | 0 | 0 | 0 |
| pik_rate | 9 | 8 | 8 | 0 |
| spread | 792 | 189 | 37 | 152 |
| Total | 1,552 | 613 | 461 | 152 |

Read now: Ares whole-coupon PIK coupons (273, fix round 1), BCRED fixed coupons (72 + 7 unpublished), Blue Owl fixed
coupons (36: 19 as before and 17 of the 21 "Ref. Rate N/A" rows read as fixed since fix round 1), Apollo label-only rates (21 all-in, 8 PIK, 16 spreads), HPS 5, Ares 2 others.
The 152 that differ are all `printed_total_margin_not_read` (section 7). Not read: PIK-only coupons of Blue Owl 70 and
HPS 62 (no whole-coupon rule there; need the row class: slice C), cash legs (no accepted rule reads one), Blue Owl PIK
margins (199). (The first version of this table said 607 interest-rate rows; the count is 606.)

## 9. Row corrections against the rules (`q_t3_corrections.sql`)

No correction differs from a rule reading. Agrees: interest rate 29, spread 13, PIK 82, reference rate (deferred,
field_not_held) 241, coupon type (deferred) 244. Both empty 338. The rule reads nothing where the correction has a value:
spread 96 (83 HPS, PIK-margin-as-spread corrections), PIK 69, interest rate 17 (11 because the printed value differs
from the tag, so the tag-first rule leaves it unread; production applied a correction there). No ruled cell: 9.

## 10. Item 13: notes printed under a schedule (STOPPED; design only)

Found (read-only; not checked by a person): Ares' note "(7) Variable rate loans ... bear interest at a rate that may be
determined by reference to SOFR or an alternate base rate (commonly based on the Federal Funds Rate or the Prime
Rate)..." is a plain `<div>` after the schedule table in the cached HTML (seen in `000162828026067383.html`, twice: the
2026-09-30 and 2025-12-31 schedules). It sits among sibling notes; note (6) and (8) are wrapped in `ix:footnote` (so they
reach `stg_filed_footnote`), note (7) is not. The filed-layer parser (`filed_parser/inline.py` `_extract`) keeps only
rows of tables holding a tagged fact (`document_row`), fact placements and `ix:footnote` elements, so the note is
dropped. It is in no filed parquet of any Ares accession (`document_row.cells`, `footnote.text`).

Why stopped: capturing it needs a new filed table, a parser version bump (3 -> 4), a re-parse of all 86 cached filings
and changes to manifest tie tests, plus owner approval of the table's scope. That is at the half-day limit and touches
the version-bound filed layer. Smallest safe design:

- New table `schedule_note` (accession, note_index, after_table_index, text first 4,000 characters, text_length,
  text_sha256, in_ix_footnote): each `<div>`/`<p>` with text, outside every table, after a kept table and before the
  next table or heading. Existing tables unchanged, so their content hashes do not move.
- Files: `filed_parser/inline.py`, `filed_parser/store.py` (TABLES entry, key, rows), `filed_parser/__init__.py`
  (PARSER_VERSION 4), `pytests/test_store.py` (version test), `pytests/test_inline.py` (a capture test and a
  false-positive test: a paragraph before the schedule, a note inside a table), a `stg_filed_schedule_note` view,
  `tests/filed_manifest_row_counts_match_tables.sql`, `docs/filed_layer.md`.
- Run `parse.ps1 --reparse` once (input sha256 values are of raw files and do not change), then feed the table into
  `int_text_check_legend` as a second legend source.
- Even captured, this note names no single benchmark for "Base Rate" (it lists SOFR, fed funds and prime); item 13's
  answer (store "Base Rate" as printed) stands.

## 11. Judgement calls

1. Item 13 read as: "Base Rate" and "CAD Base Rate" are stored as printed (reference_rate rows of kind base, no
   series); "Equity plus" and "Variable" are not codes.
2. A legend entry is not carried across a filing whose own legend gives the code two names (item 2: "where no filing
   contradicts it"). Effect: BCRED S in 2022-09-30 (10 positions) and Blue Owl C before 2024-12-31 (15) are unread
   instead of read as SONIA and CORRA. Without it Blue Owl C would read CORRA in quarters before CORRA loans
   replaced CDOR (production: CDOR, its dated rule); the base level cannot tell (one proxy series).
3. Tag first: a printed value that differs from the filer's tag of the same field is not read (differs_from_tag) unless
   a printed_wins rule covers the row. Listed, 31 positions.
4. Item 7 is applied per shape with fewer than 5 positions, both orders agreeing, no tagged row differing and no leg
   identity failing on any role. A rare shape's floor is graded untested (item 5).
5. A shape partly accepted is read partly: the accepted roles and its floor; other roles stay unread.
6. Rule grade where two rules give one value: the strongest (checked, matches_few_rows, owner, untested).
7. Constraint 5 takes the read all-in rate, else the all-in tag; it skips PIK legs, as the base-level check does.
8. "Code printed but unread" counts as no reference rate for constraint 1 (the spread is dropped, detail says why).
9. The fixed-rate check compares only positions with no code read anywhere on the row; this keeps Ares' "Spread"
   column (code in "Reference") out of it.

## 12. Tests and build

Unit tests: proposed read with a case variant (p10); leg identity d not_testable on tags, still failing on print
(p14 to p16); verdict relabel by the fixed-rate check; fixed-rate check and its false-positive guard (a coded spread and
a code-elsewhere spread never become fixed); legend lookup (two names, unresolved, no CDOR/CORRA leak); cell reading
(roles, basis points, own legend, two-name legend, table nearest, not carried across a two-name filing, self-named,
not a code); constraints A1 to A3 each dropping a real error; A4 and A5 failing a real error. Data tests: keys
(`int_text_rate_read_keys_unique.sql`), A1 to A3 on the output (`int_text_rate_read_constraints.sql`), every code
mapping resolves to `reference_rate` (`reference_rate_rule_resolves.sql`), grades and statuses accepted values.
Baselines: `int_text_rate_unread_groups` 41, `int_text_rate_constraint_fail` 306, `int_text_rate_constraint_dropped`
102.

Results (2026-11-26):

- Full build (`dbt.ps1 build --threads 2`, log `scratch/2026-11-26_text_slice_r3/full_build.log`): `PASS=1137
  WARN=129 ERROR=0 TOTAL=1266` (fix round 1: 1084 / 126 / 0 / 1210; new warnings: the three phase 3 baselines).
- pytests (`warehouse/pytests`): 181 passed (180 before; one loader test added).
- CI fixture (`ci/run_fixture_build.py`, new folder): step 4 `PASS=3`; build `PASS=730 WARN=5 ERROR=0 TOTAL=735`;
  empty run `PASS=2`; unit-test and drift step `PASS=75`.

## 13. Not known

- Whether any reading is right on the printed page: no page was opened.
- Which dollar rate a code is where the legend is silent (item 1 self-named codes and item 4 letters rest on the owner).
- Blue Owl and Apollo: no all-in rate, so constraint 5 tests nothing there.
- Why production holds Blue Owl SR as LIBOR on 4 positions, and the 8 rate-type differences labelled not traced.

## 14. Fix round 1 (review of 553600d4, 2026-11-26)

Reviewer queries `scripts/text/review_p3_r2_*.sql` (not committed). This section holds where it disagrees with sections
1 to 13; sections 7 and 8 and the constraint-5 paragraph of section 6 were regenerated in place. Still nothing
published, no page read; a pass is consistency with the filer's tags, legend or public series, not correctness.
Controller rulings below were made under the owner's items, recorded as such.

| # | Item | Before | After |
|---|---|---|---|
| 1 | Constraint 1 with a printed code no rule resolves | 64 spreads dropped (`code_printed_unread`: BCRED 23, Blue Owl 18, Apollo 5, HPS 18), all equal to the spread tag | A printed code (read or not; "Equity plus" and "Variable" are not codes) counts as a reference rate for constraints 1 and 2; those spreads are read; the reference rate stays unread, status `code_undecided`, `reference_rate_detail` the cell status (BCRED 23, Blue Owl 18, Apollo 5, HPS 18). Readings dropped in all: 102 -> 5 |
| 2 | Fix 1a in the base-level check | 25 rows excluded (Apollo 5, BCRED 18, Ares 2) | Excluded only where no printed all-in rate agrees with the tag: 5 (Apollo). The 20 BCRED and Ares rows are tested again (17 zero-base rows, 3 LIBOR contradictions); no proposal verdict changed. Identity d already used the tag only where no all-in rate is printed (unchanged, 8). New baseline `baseline_int_text_all_in_tag_is_leg` lists every excluded row: 18 (d 8, base level 5, constraint 5 5) |
| 3 | Ares "Coupon" printed "#% PIK" (owner item 9; controller ruling) | read as PIK rate only | Rule flag `whole_coupon`: the number is the all-in rate and the PIK rate; no cash rate written; `all_in_source` pik_coupon on 1,544 positions. Constraint 4 extended: with no cash rate read, the implied cash leg (all-in less PIK) must not be negative. Before 0 rows; after 4,310 rows, 0 fail (Ares 1,250 implied cash + 1,543 whole coupon, BCRED 908, HPS 608, Apollo 1). A whole-coupon row passes by construction; the test bites on the 2,767 rows printing an all-in rate and a separate PIK rate |
| 4 | Legend against the dated code table (owner item 3) | no test | `tests/text_legend_disagrees_with_code_table.sql`, error severity: 0 rows. The generator now refuses to write (exit 2, lists the entries) when a new legend contradicts an existing dated entry, unless rerun with `--accept-legend-change`. That refusal path was not exercised: no contradiction exists today |
| 5 | Grade of the 9 BCRED printed_wins values | checked | owner (the printed_wins rule's grade) |
| 6 | Unread baseline | ceiling on 41 groups only | Seed `text_rate_unread_cap` (unit, shape, status, positions; written by `q_t3_unread_cap.sql`) and test `int_text_rate_unread_within_cap`: a group that grows or is new fails |
| 7 | Blue Owl "Cash" number where "Ref. Rate" prints N/A (owner item 11, Blue Owl ruling; controller ruling) | 21 spreads dropped by constraint 1 | Conditional rule (condition column "Ref. Rate", text N/A): fixed rate, grade untested, no spread. Blue Owl fixed rates 19 -> 40 |
| 8 | BCRED [7bedc6] "#%" | spread rule, checked (5 positions; the spread tag matched 5 of 5, the all-in tag 4 of 4) | Fixed rate, grade matches_few_rows. How the check missed it: the fixed-rate check confirmed only at 5 rows, so below the bar the old spread label stood, accepted by the spread tag the filer also files. Closed generally: new verdict `fixed_rate_few_rows` (1 to 4 compared rows, every one equal to the all-in tag) relabels the role fixed_rate_pct (verdict needs_owner, too few rows) and the generator grades it matches_few_rows (items 11 and 7). BCRED fixed 478 -> 483; BCRED rate_role rules checked 69 -> 68, matches_few_rows 34 -> 35 |
| 9 | Apollo "#% Cash plus #% PIK, #% Floor" | its floor ruled, then dropped by constraint 2 | No rule for any role of a shape with an unstable or contradicted role; listed unread. Apollo rate_role untested 54 -> 53; Apollo floors held 11 -> 4 |
| 10 | K3 held values | a count only | `int_text_rate_held`: (position, field, value, rule, constraint): 5 rows (Ares 1 spread "8.00%" with no code; Apollo 4 floors on rows with no code, e.g. "12.50% (includes 6.25% PIK), 1.00% Floor") |
| 11 | K4 findings | none | `int_text_rate_finding`: one row per (fund, constraint, rule), id = first 16 hex of md5(cik, constraint, rule id), with positions, dates and an example. 58 findings: Ares 8 (A1 1, c5 7), BCRED 41 (c5), Apollo 2 (A2), HPS 7 (c5). Unique id tested. Stability across two runs is NOT tested: the CI fixture has no rate-text rules, so its finding table is empty. Correction (fix round 2): the id was NOT stable; it hashed the loader's rule_id, which covers evidence, counts and dates. See section 15 |
| 12 | Section 7 table | did not reproduce | regenerated from the database |
| 13 | The 152 spread differences | "PIK margin is the PIK spread" | Production = spread + the PIK number on all 152; the number is read as `pik_rate` here. Two open owner questions in section 7 |
| 14 | Constraint 5 "mostly 2022" | unquantified | 168 of 306 in 2022 (after fix round 1); the 64 SOFR failures 2024 to 2026 are not explained |
| 15 | Rare shapes with no tagged row | owner sheet: 2 shapes, 5 positions | At 553600d4: 3 shapes, 7 positions. After item 9: 2 shapes, 5 positions (Apollo "Equity plus #% PIK" 2 and "Equity plus #% PIK, #% Floor" 3) |
| 16 | The 1,772 figure | "could not be reproduced" | Cannot be traced; 1,552 (1,407 positions) used |

Headline counts after fix round 1 (all positions; section 3 numbers before):

| Measure | Before | After |
|---|---:|---:|
| Readings not applied (constraints 1 to 3) | 102 | 5 |
| Reference rates `code_undecided` | (counted as not printed) | 64 |
| Spreads read, BCRED / Blue Owl / Apollo / HPS | 22,640 / 8,254 / 7,185 / 6,294 | 22,663 / 8,272 / 7,190 / 6,312 |
| Fixed rates, BCRED / Blue Owl | 478 / 19 | 483 / 40 |
| Ares all-in rates read | 13,687 | 15,231 |
| Constraint 4 rows (fail) | 0 (0) | 4,310 (0) |
| Constraint 5 failures | 306 | 306 |
| Rates production holds and this layer left unread, now read (equal / differ) | 322 (170 / 152) | 613 (461 / 152) |
| Unread groups | 41 | 41 |
| Findings | - | 58 |

Results (fix round 1):

- Full build (`--threads 2`, log `scratch/2026-11-26_text_slice_r3/full_build_fix1.log`): `PASS=1152 WARN=130 ERROR=0
  TOTAL=1282`.
- pytests: 181 passed (a first run failed `test_no_fund_names_in_sql` on two comments that named funds; fixed, rerun
  181 passed).
- CI fixture: step 4 `PASS=3`; build `PASS=745 WARN=5 ERROR=0 TOTAL=750`; empty run `PASS=2`; unit-test and drift step
  `PASS=75`.

## 15. Fix round 2 (change-only review of 2993d521, 2026-11-26)

Reviewer queries `scripts/text/review_p3_r3_*.sql` (not committed). Section 15 holds where it disagrees with earlier
sections. Still nothing published and no page read.

| # | Item | Before | After |
|---|---|---|---|
| 1 | Finding ids | `md5(cik, constraint, rule_id)`; rule_id is the loader's hash over every column, evidence wording, counts and filing dates included: 50 of 58 findings named such a rule, and fix round 1 re-hashed the Ares "Coupon" rules by editing their evidence | `md5(cik, constraint, rule_key)`. `int_text_rate_rule.rule_key` hashes only fund, action, table and header signature, shape, number index, role and the condition (rate_role); code and rate (rate_code, rate_text_not_a_code); field, table index, printed rows and filing (rate_printed_wins, whose scope is one filing). Never evidence, counts, filing dates or the evidence filing. The readings with no wrapper rule (`reference_rate:<rate>`, `owner-2026-11-26-item-2`) are their own key. Unit tests: `int_text_rate_rule_key_ignores_evidence_counts_dates` (two code rules differing in evidence, dates, evidence filing and grade, two role rules differing in evidence counts and grade: one key each) and `int_text_rate_finding_stable_id` (rules sharing a key make one finding). Findings: 58, ids unique. Still not tested across two runs of a real build |
| 2 | Constraint 4 unit rows | no failing row for the new branch | p7 all-in 6.00, PIK 8.00, no cash rate: fail; p8 whole coupon 10.00 = 10.00: pass. What the branch can catch: a PIK reading above the all-in reading (a negative cash leg). What it cannot: an all-in reading that is really the cash leg (cash + PIK printed, the cash part read as the all-in rate: PIK below it passes), a wrong number of the right size, and a whole-coupon row, which passes by construction |
| 3 | Ares 2025-06-30 "19%" whole coupon | PIK reading blocked (differs from the PIK tag 12.29) but the same number applied as all-in 19.00 | The all-in rate stands only if its PIK reading is applied; this row is now status `whole_coupon_pik_not_applied`, unread (Ares whole-coupon positions applied: 1,543 of 1,544). Unit row p10 |
| 4 | Undated code rules (3: Ares Base Rate and CAD Base Rate, Blue Owl L) | not protected | The generator's `legend_conflicts` and `tests/text_legend_disagrees_with_code_table.sql` include undated entries (they hold at every date). Today: dated 0, undated 0 contradictions. New pytest `test_accepted_rules_generator.py` (4 tests, made-up wrappers in a temporary folder): a dated and an undated contradiction each exit 2 and write nothing; an extension with the same rate is written; `--accept-legend-change` writes over a contradiction. The generator's write step is now a function `write_wrappers` so it can be tested; real wrappers unchanged (`--check` exit 0) |
| 5 | Unit tests | no case for `fixed_rate_few_rows`; p9 expected neither `pik_rate` nor `all_in_source` | `int_text_check_fixed_rate_false_positive` gains u4 (3 code-free rows, all equal to the all-in tag: fixed_rate_few_rows, label changes) and u5 (3 rows, one differs: too_few_rows, no change). p9 now expects pik_rate 10.00 and all_in_source pik_coupon, and every row expects pik_rate, all_in_source and all_in_rate_status |
| 6 | The 20 base-level rows re-tested in fix round 1 | "17 zero-base rows, 3 LIBOR contradictions" | All 20 have an implied base of exactly zero (all-in tag = spread; `review_p3_r3_fix1a.sql`): admissible 15 (EURIBOR 2022: Ares 2, BCRED 5; SARON 2025-26: BCRED 7; CDOR 2022: BCRED 1), outside 5 (LIBOR 2022-23: BCRED 3; SOFR 2022: BCRED 2). No proposal verdict changed: `q_t3_verdict_changes.sql` (against the verdicts saved before phase 3) lists as code changes only Apollo S=SOFR in two columns, the same list as at 553600d4, so no BCRED or Ares code verdict moved at fix round 1 or at phase 3 |
| 7 | Ares all-in new against production (1,148) | "likely the 838 non-loan rows" | Reproduced (`review_p3_r3_ares_newonly.sql`, `review_p3_r3_ares_pik.sql`): 1,148 = 1,130 whole-coupon + 18 ordinary readings. Of the 1,130, by production's class: preferred equity 711, common equity 173, fund 9, loans 237 (227 term loans, 10 revolvers). Production holds the same number as `pik_rate` with no `interest_rate` on 1,129 of them (preferred 710 of 711). The owner question on class covers the 893 equity and fund rows only; on the 237 loans the whole-coupon reading gives the all-in rate production leaves empty |

Results (fix round 2):

- Full build (`--threads 2`, log `scratch/2026-11-26_text_slice_r3/full_build_fix2.log`): `PASS=1154 WARN=130 ERROR=0
  TOTAL=1284`.
- pytests: 185 passed (181 plus the 4 generator tests).
- CI fixture: step 4 `PASS=3`; build `PASS=747 WARN=5 ERROR=0 TOTAL=752`; empty run `PASS=2`; unit-test and drift step
  `PASS=77`.
