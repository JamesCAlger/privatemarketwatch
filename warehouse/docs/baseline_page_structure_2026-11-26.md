# Baseline: page structure (text slice P, 2026-11-26)

Branch `warehouse-text-spec`. Plan: `docs/2026-11-26-text-plan.md`, slice P, tasks P1 to P4 (P5 not done here).
Queries: `scripts/text/q_p1_*.sql`.

**Nothing here says a value is correct. No page was read by a person.** The models say where the filer's inline
document puts things; counts below are measurements of the filed layer, not checks against the printed filing.

## 1. What each model decides

| Model | Decides |
|---|---|
| `int_page_position` | For each position (published or not), the printed row of the fair-value fact `int_field_read` reads: visible placements only. `one_row`, `several_rows` (no row taken), `not_placed` |
| `int_page_table` | A schedule table = a printed table holding at least one position's printed row. Width = modal summed colspan. Header lines (rules below) |
| `int_page_cell` | True columns of every non-empty cell: colspans summed (0-based); a rowspan from the row directly above resolved by laying the row's cells into the free columns; a span from further up flagged `deeper_span`, columns left naive. `row_width_ok` |
| `int_page_column` | Leaf columns under the header: printed span, zone (to the next leaf), header text, sub-header text, signature |
| `int_page_schedule` | (fix round 1) Which page tables form one schedule: a new schedule starts at a change of the table's ordered header signature, a new normalised title, or a non-schedule table in between |
| `int_page_cell_column` | Each data cell's column and the rule that gave it: `zone`; `prefix_of_next` (a currency marker followed by a number takes the number's column); `trailing_footnote` (footnote marks past their leaf's printed columns go to an unheaded `#footnote_marks` column); `none_row_width_differs`; `none_left_of_first_leaf`. The cell's shape |
| `int_page_column_filing` | Per filing, table signature and column signature: tables, data cells by shape (shares exclude footnote marks, counted apart), placed facts by concept. Counts only |
| `int_page_heading` | Heading rows: no facts, exactly one non-empty cell, below the header. Their schedule, the run of consecutive headings (blank rows and a repeated header at a page break do not end a run), `run_length`, `run_position`, `depth_from_bottom`; since fix round 2 `norm_text`, `is_page_top_run`, `is_continuation` and `level` (the most frequent depth of its normalised text in the schedule, continuations left out). Features `is_continued`, `next_row_kind`, `seen_in_prior_filing` |
| `int_position_heading` | For each level 0 to 3 (fix round 2), the nearest heading above the position at that level in its schedule, unless a higher-level heading that is not a continuation lies between; rank by distance, distance, same-table flag |

Header rules (`int_page_table`): candidates are rows with no facts, above the table's first position row, with at
least 3 non-empty cells. One candidate: `one_line`, unless the next row (no facts, above the first position, at least
2 non-empty cells) is a sub-header line (`line_below`), or the row directly above (no facts, no rowspan, 1 or 2
non-empty cells, each covering at least 2 and not all of the candidate's cells) is a group line (`group_line_above`).
Two candidates on consecutive rows: `two_candidates`. None: `none`. Anything else: `ambiguous`, no header taken.

## 2. Counts per fund

All parsed filings of the five funds. "Positions" counts published positions; tables include joint-venture schedules.

| | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| Published positions | 21,191 | 15,531 | 10,527 | 8,034 | 8,442 |
| placed in one row | 21,191 | 15,531 | 10,527 | 8,034 | 8,442 |
| several rows / not placed | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Filings | 17 | 16 | 15 | 15 | 14 |
| Schedule tables (with a published position) | 990 (990) | 1,014 (637) | 423 (377) | 550 (550) | 250 (230) |
| Median / max rows per table | 31 / 41 | 35 / 73 | 40 / 83 | 32 / 53 | 51 / 55 |
| Header found: one line | 989 | 1,014 | 219 | 550 | 250 |
| two lines (two candidates / line below / group above) | 0 | 0 | 204 (115 / 34 / 55) | 0 | 0 |
| no header | 1 | 0 | 0 | 0 | 0 |
| Non-empty cells | 227,873 | 283,175 | 117,361 | 84,408 | 78,308 |
| Rows width not the table's | 0 | 0 | 31 | 0 | 0 |
| Cells of rows placed by the rowspan rule | 0 | 0 | 478 | 0 | 0 |
| Data cells / not assigned to a column | 214,803 / 0 | 273,153 / 0 | 113,538 / 0 | 80,558 / 0 | 75,987 / 0 |
| Distinct header signatures | 13 | 13 | 21 | 8 | 11 |
| Heading rows / distinct texts | 391 / 42 | 4,971 / 161 | 1,156 / 56 | 5,202 / 751 | 1,135 / 111 |
| Headings marked continued | 0 | 1,217 | 0 | 0 | 0 |
| Headings not seen in the prior filing | 29 | 202 | 28 | 620 | 114 |
| Schedules per filing (filings) | 1 (16), 2 (1) | 2 (1), 3 (15) | 2 (15) | 1 (15) | 1 (3), 2 (2), 3 (9) |
| Heading runs of length 1 / 2 / 3 (heading rows) | 391 / 0 / 0 | 2,729 / 2,008 / 234 | 935 / 92 / 129 | 3,650 / 1,552 / 0 | 818 / 224 / 93 |
| Published positions with a heading at level 0 / 1 / 2 (fix round 2) | 21,190 / 0 / 0 | 15,531 / 15,531 / 15,530 | 10,527 / 8,256 / 8,256 | 8,034 / 8,034 / 0 | 8,442 / 8,442 / 8,442 |
| Data cells by rule: prefix_of_next (moved) / trailing_footnote / none_row_width_differs | 75 (0) / 19,952 / 0 | 3,056 (0) / 0 / 0 | 1,970 (0) / 0 / 85 | 4,752 (262) / 8,329 / 0 | 1,395 (16) / 0 / 0 |
| Column units (re-keyed) / table kinds | 238 / 17 | 236 / 25 | 241 / 30 | 120 / 15 | 148 / 23 |

Notes: Ares prints each industry heading once per filing, so most positions take it from an earlier page table.
Apollo's 751 distinct headings mix industries and issuer brands (as the spec, 4.1a, says). The P0 counts of
2026-11-25 (2,270 Blue Owl positions unplaced, 1 Ares in several rows) do not hold with the fact `int_field_read`
reads (section 6, item 1). The one table with no header: Ares 0001287750-23-000021, table 91, 28 rows, first position
on its 18th row, one published position (`baseline_int_page_position_no_column` 1).

The 31 rows whose width differs (all Blue Owl): 18 header rows of its width-54 tables (the header's colspans sum to
less than the data rows'), 12 "Total ..." rows and 1 heading row in its two-line-header tables (all in 0001812554-26-000060, 2026-09-30). The P0 count of
153 rows included rows with no text and the 115 second header lines the rowspan rule now places. Rows needing a
deeper span: 0.

## 3. Header signatures between consecutive filings

Changes in a fund's set of signatures from one filing to the next (`scripts/text/q_p1_signatures.sql`):

| Fund | Consecutive pairs | Pairs with a change | Changes |
|---|---:|---:|---|
| Ares | 16 | 0 | none |
| BCRED | 15 | 5 | 2023-03-31 "footnotes" added, "paramount/units" gone; 2023-06-30 back, "paramount" gone; 2024-09-30 "acquisitiondate" added; 2024-12-31 and 2025-03-31 joint-venture capital column relabelled |
| Blue Owl | 14 | 3 | 2024-12-31 unfunded-commitment table appears; 2025-03-31 "interest" splits into ref. rate / cash / PIK, "percentageofnetassets" becomes "%ofnetassets"; 2026-03-31 "par/units" splits into "par" and "units" |
| Apollo | 14 | 1 | 2025-12-31 "par/shares" becomes "par/shares/units" |
| HPS | 13 | 1 | 2024-06-30 unfunded-commitment table appears |

These are the units that would trigger "changed" in spec 4.2. Whether each needs a new rule was not decided.

## 4. Tests

Build of record after fix round 2 (2026-11-26, `.\warehouse\dbt.ps1 build --threads 2`, 2 threads for memory as in fix round 1): `PASS=904 WARN=119 ERROR=0 TOTAL=1023`. CI fixture after fix round 2: step 4 `PASS=3`; build `PASS=497 WARN=5 ERROR=0 TOTAL=502`; empty run `PASS=2`; unit-test and drift step `PASS=52`. After fix round 1: `PASS=903 WARN=118 ERROR=0 TOTAL=1021`, run with `--threads 2`: the first fix-round build (4 threads) was stopped by the machine running low on memory at step 531 (`int_page_cell`); with 2 threads it passed. First commit (7ca1b4f1):
`PASS=891 WARN=117 ERROR=0 TOTAL=1008`. CI fixture after fix round 1 (`ci/run_fixture_build.py`, local, new folder):
step 4 `PASS=3`; build `PASS=496 WARN=5 ERROR=0 TOTAL=501`; empty run `PASS=2`; unit-test and drift step `PASS=52`.

- Column tests (not_null, accepted_values) on the nine models; `tests/int_page_keys_unique.sql` (every key, and a row
  per position of `int_source_row`).
- Eight unit tests: cumulative columns and the rowspan rule (a deeper span flagged, a no-break space); the header
  forms and the title; the leaves of a two-line header; the column rules (a currency marker inside another column's
  zone moved to the number's column, a marker before text left alone, a trailing footnote mark, a row of the wrong
  width given no column); schedule boundaries (header change, first title, same title normalised, non-schedule table
  between); heading detection with runs and levels (a run kept across a page break, broken by a schedule; a
  "(continued)" repeat at the same level; a page-top continuation that drops a level keeping its texts' levels; a lone
  heading that leads a longer run elsewhere taking the higher level); headings by level (the section kept behind
  sibling headings, the reset firing, a continuation not resetting, no carry into the next schedule); bracketed digits
  ("(110)" with a fact, "(110)" in a numeric column, "(4)" in the footnote gap, "(4)(5)"). The rowspan test was shown to fail with one
  expected column changed (first commit).
- Eight baselines with ceilings in `dbt_project.yml` (`baseline_max`): `int_page_position_not_placed` 0,
  `int_page_position_several_rows` 0, `int_page_cell_row_width` 31, `int_page_cell_deeper_span` 0,
  `int_page_table_no_header` 1, `int_page_position_no_column` 1, `int_page_field_split_columns` 35 (was 27),
  `int_page_field_fact_no_column` 36, and since fix round 2 `int_position_heading_sibling_sections` 23.

Field split (35 table-field pairs, any row role since fix round 1; macro `page_field_fact`): HPS 26, Ares 4, Apollo 3,
BCRED 2. Rate cases: the filer prints the odd value in the neighbouring rate column ("13.75% PIK" in "Reference Rate and
Spread"; the coupon "12.55% (4.13% PIK)" carrying the spread tag under "Coupon"). The 8 new pairs: 2 Ares spread
tables where non-position rows carry the same pattern, 1 more HPS pair, and 3 Apollo tables where a cost-tagged value
on a non-position row sits under "par/shares" (e.g. 126,725). Detail: `scripts/text/q_p1_split_detail.sql`.

## 5. Fix round 1 (independent review, 2026-11-26)

| # | Finding | Change | Measured after |
|---|---|---|---|
| 1 | The nearest-4 cap dropped section headings behind sibling headings | Runs of consecutive headings in `int_page_heading` (`run_length`, `run_position`, `depth_from_bottom`); `int_position_heading` takes the nearest heading per depth 0 to 3, dropped if a deeper heading lies between | Published positions with a "...controlled..." heading above them in their schedule but none kept: BCRED 40 (was 3,697), Blue Owl 0 (was 8,007), HPS 0 (was 7,946). Ares and Apollo have no such headings |
| 2 | Headings carried across the end of a schedule | `title_text` on `int_page_table`; new model `int_page_schedule` (`schedule_seq`); no carry across schedules | Headings carried between tables of published and unpublished positions (`review_p_cross_pub.sql`): 0. Before: the reviewer's counts BCRED 108/223, Blue Owl 35/77, HPS 14/43 at ranks 3-4; with titles alone (no gap rule) HPS still 119 |
| 3 | Currency marker before a number fell under the previous column | `column_rule` `prefix_of_next` | Marker cells whose column differs from the next number's (`review_p_ccy_split.sql`): 0 (was Apollo 262, HPS 8). Moved: Apollo 262 ("$" 164, "€" 47, "£" 39, "A$" 4, "kr" 4, "₣" 4), HPS 16 ("S$" 8, "kr" 8) |
| 4 | Total rows of one fund land one column group left | Rows with `row_width_ok` false get no column (`none_row_width_differs`); the split check reads every placed field fact on any row | 85 cells given no column; 36 field facts on them (cost, fair value, share of net assets, 12 each) counted by the new baseline; split 35 |
| 5 | `int_page_column_filing` mixed tables | Re-keyed on (accession, table_signature, header_signature); shares exclude footnote marks; trailing footnote marks get the unheaded column `#footnote_marks` | Units 238 / 236 / 241 / 120 / 148 (Ares / BCRED / Blue Owl / Apollo / HPS). Unheaded footnote cells: Ares 19,952, Apollo 8,329; footnote marks still under a header: BCRED 22,238, Blue Owl 1,995, Apollo 2,509, HPS 2,399 (the last three were negative amounts; corrected in fix round 2, section 5a) |

Row 1's "BCRED 40" was re-run by the reviewer as 39 (the same filing); fix round 2 below brings it to 0.

## 5a. Fix round 2 (change-only review, 2026-11-26)

| # | Finding | Change | Before -> after |
|---|---|---|---|
| A | Bracketed digits such as "(110)" (negative amounts carrying cost and fair-value facts) were classed as footnote marks | In `int_page_cell_column`: a single bracketed group of 1 to 3 digits is a number when a fact is placed in it, or, with no fact, when its column (table signature, zone signature, same side of the leaf's printed columns) holds placed numeric facts in other cells; otherwise a footnote mark. Two or more groups stay footnote marks | Footnote-mark cells holding a fact: Blue Owl 1,998 -> 0, Apollo 2,509 -> 0, HPS 2,399 -> 0. Footnote marks: Ares 19,952 -> 19,952 (all in the unheaded column), BCRED 22,238 -> 22,238 (its "Footnotes" column), Blue Owl 1,998 -> 0, Apollo 10,838 -> 8,329 (all unheaded), HPS 2,399 -> 0. Numbers: Blue Owl 39,313 -> 41,311, Apollo 26,565 -> 29,074, HPS 31,504 -> 33,903; Ares 71,752 and BCRED 107,800 unchanged |
| B | Depth from the bottom of a run gave wrong but plausible stacks (a page-top continuation that drops a level; "Equity (continued)" over "Equity"; a stale sibling section) and the reset never fired | `int_page_heading` adds `norm_text`, `is_page_top_run`, `is_continuation` and `level` (rules in its header; `depth_from_bottom` stays as a feature). `int_position_heading` keeps the nearest heading per level 0 to 3, dropped if a higher-level heading that is not a continuation lies between | Table below |

Heading checks on published positions (`scripts/text/q_p2_heading_metrics.sql`; before = fix round 1 by depth, after =
by level):

| Check | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| Same normalised text at two levels | 0 -> 0 | 137 -> 0 | 0 -> 0 | 0 -> 0 | 0 -> 0 |
| Levels 1 and 2 both name controlled/affiliated, different texts (pattern B) | 0 -> 0 | 4 -> 4 | 10 -> 10 | 0 -> 0 | 9 -> 9 |
| "...controlled..." heading above in the schedule, none kept | 0 -> 0 | 39 -> 0 | 0 -> 0 | 0 -> 0 | 0 -> 0 |
| No level-0 heading | 1 -> 1 | 0 -> 0 | 0 -> 0 | 0 -> 0 | 0 -> 0 |
| Level-0 text kept at level 1 for another position of the filing | 0 -> 0 | 98 -> 0 | 0 -> 0 | 0 -> 0 | 0 -> 0 |

- The reviewer's wider stale-parent query (`scripts/text/review_p2_hps_d2.sql`: a level-1 heading naming an affiliation
  whose level-2 heading is not a prefix of it) is unchanged: BCRED 287, Blue Owl 10, HPS 74. Part of it may be real
  parents (BCRED "Equity and other" over "Equity - non-controlled/non-affiliated", 138 + 35 + ...); structure cannot
  tell.
- The reset is live (unit test `int_position_heading_by_level`, p9) but drops no heading in today's data: with levels
  per schedule every new higher section comes with its own lower headings (`scripts/text/q_p2_reset_fires.sql`; 156
  BCRED positions were dropped while levels were per filing). Level differs from depth on 10 headings, all BCRED
  continuations.
- Level is computed per schedule, not per filing as the brief said: across a filing, the joint-venture schedule's
  shorter stacks gave the fund's "First Lien Debt" level 1 instead of 2 (7,401 BCRED positions lost their level-2
  heading in the first try).
- Left, counted, not fixed: pattern B, 23 published positions (Blue Owl 10, HPS 9, BCRED 4), ceiling
  `int_position_heading_sibling_sections` 23. A section printed without the upper heading of its stack (for example
  "Controlled/Affiliated Investments" in a shorter run than the earlier "Non-Controlled/Affiliated Investments") gets a
  lower level from its own runs, so it neither replaces nor drops the older section. Telling a sibling from a parent
  needs the headings' meaning, which belongs to a later slice with a per-fund rule.
- Ares has only single industry headings (level 0); its 1 position with no heading is the table without a header.
  Apollo: industry (level 1) over brand (level 0) in every filing seen; level-0 texts never appear at level 1 in the
  same filing (0). Blue Owl's 2,271 unfunded-commitment positions sit under single headings, level 0 only.
## 6. Known, not a slice P matter

- 2,271 Blue Owl published positions from 2024-12-31 to 2026-09-30 have their fair-value row only in the
  unfunded-commitment table, and no cost placed anywhere (`scripts/text/review_p_unfunded.sql`). Whether they belong in
  the position set is a row-scope question for the owner (the open D11 / D15 item on commitment lines).
- BCRED's rowspan-2 title rows (a title cell spanning 2 rows over a blank row, e.g. 0001803498-22-000021 rows 3175 to
  3176) sit above the header line. The blank row it covers has no text, so it is not in `int_page_cell`, is not
  counted in the row-width baseline and is not a data row. Nothing is pushed past the table width that any later model
  reads.

## 7. What is not known

- Whether any cell sits in the right column on the printed page: no page was opened. The field-split test is the
  only cross-check (field facts under one column per table), and it cannot see a column that is consistently wrong.
- Headings: nothing says which are industries, sections, issuers or brands. Level is a structural reading of each
  text's usual depth in its schedule; section 5a lists where it is known to slip.
- Schedule boundaries are found from headers, titles and gaps between tables; a second schedule with the same header,
  no title inside its tables and no table between would not be found.
- Subtotal rows under a heading were not compared with the rows beneath (plan P4 check). Not built.
- Tables without a header lose their cells' columns; one table today.
- The CI fixture has a schedule, but whether its page shape exercises every branch was not checked; the unit tests
  carry the logic.

## 8. Judgement calls

1. Positions: the fair-value fact is the one `int_field_read` reads, not a concept-name match. This is why the P0
   count of 2,270 unplaced positions (one fund, 2024-12-31 to 2026-09-30) is 0 here: their fair value is read from the
   fund's own concept (fair value net of unamortized fees) under a fund rule, and every such fact is placed. The P0
   "several rows" case is also 0: the read fact is in one row.
2. Hidden facts: their shown row is not used to place a position. For the column counts and the split test, a hidden
   fact counts in the cell that shows it (as `int_rate_tag_cell` does).
3. Schedule tables include unpublished positions' tables (joint-venture schedules), so table counts are higher than
   P0's published-only counts. Baselines on positions count published rows only.
4. Width ties go to the larger width. Non-positive or missing colspans count 1.
5. Rowspan cells straddling an occupied column take the free column at their last position (no straddle seen).
6. Two-line headers: added `line_below` and `group_line_above` beyond the brief's "second line directly under the
   first". Without them one fund's header changed signature in 2025-12-31 (a group line "Interest" above the header
   instead of a first line spanning two rows), and its unfunded-commitment tables lost the sub-headers "Commitment |
   Fair Value". A title above the whole table is excluded by the "not all cells" condition.
7. Leaves: a lower-line cell under no upper cell is its own leaf with its own text as header; a header cell with no
   letter or digit (spacer "." cells of one fund) is ignored.
8. Zones: a data cell belongs to the leaf whose zone contains its first column; a zone runs to the next leaf. Since fix
   round 1 two rules come first: a currency marker before a number takes the number's column, and a footnote mark past
   its leaf's printed columns goes to the unheaded column.
9. Signatures: lower case, digits in brackets removed, white space removed; two-line leaves join with "/".
10. Shapes: added `footnote_mark` (spaces inside brackets allowed since fix round 1) beside the brief's five.
11. Headings only in tables with a header; `next_row_kind` looks within the table and skips rows with no text;
    `end_of_table` is a fourth value. `seen_in_prior_filing` compares exact text with the fund's previous filing here.
12. Fix round 1: `schedule_seq` lives in a new model `int_page_schedule`, not on `int_page_table` as the brief asked:
    the table signature comes from `int_page_column`, which reads `int_page_table`, so putting it there would be a
    cycle. `title_text` is on `int_page_table`.
13. Fix round 1: the title rule compares with the nearest earlier title in the filing; a titled table after untitled
    ones starts a new schedule (a joint venture titled inside its tables after the fund's own untitled schedule).
14. Fix round 1, beyond the brief: a non-schedule table between two schedule tables starts a new schedule. HPS's
    joint-venture schedule repeats the main header and has no title inside its tables; measured, no such gap falls
    inside a schedule of published positions (the gaps seen: 11 HPS, 5 BCRED and 1 Ares, all at a change of schedule or
    before an unpublished table, plus Ares's table without a header).
15. Fix round 1: a run is consecutive heading rows among the schedule's data rows in document order; header lines,
    titles and rows with no text are not data rows, so a page break does not end a run.
16. Fix round 1: currency marker = `[A-Z]{0,3}\p{Sc}` or "kr" (any case), the whole cell; followed by a cell of shape
    number. ISO codes ("USD") are not markers: none was seen alone in a cell.
17. Fix round 2: a bracketed group of 1 to 3 digits is decided by the facts: a fact in the cell makes it a number; with
    no fact, numeric facts placed in the same column (table signature, zone signature, same side of the leaf's printed
    columns) make it a number; otherwise a footnote mark. The "same side" keeps footnote marks in the gap after "Fair
    Value" apart from the fair-value numbers.
18. Fix round 2: a page-top run is one whose first heading is the first data row of a table that is not the
    schedule's first; a heading in it is a continuation when its normalised text appeared earlier in the schedule.
    Continuations do not reset lower levels and are not counted when a text's level is computed.
19. Fix round 2: level per schedule, not per filing (section 5a). Ties between depths go to the larger depth.