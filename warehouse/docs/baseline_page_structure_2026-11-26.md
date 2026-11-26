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
| `int_page_heading` | Heading rows: no facts, exactly one non-empty cell, below the header. Their schedule, the run of consecutive headings (blank rows and a repeated header at a page break do not end a run), `run_length`, `run_position`, `depth_from_bottom`. Features `is_continued`, `next_row_kind`, `seen_in_prior_filing` |
| `int_position_heading` | For each depth 0 to 3, the nearest heading above the position at that depth in its schedule, unless a deeper heading lies between; rank by distance, distance, same-table flag |

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
| Published positions with a heading at depth 0 / 1 / 2 | 21,191 / 0 / 0 | 15,531 / 15,531 / 15,530 | 10,527 / 8,256 / 8,256 | 8,034 / 8,034 / 0 | 8,442 / 8,442 / 8,442 |
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

Build of record after fix round 1 (2026-11-26, `.\warehouse\dbt.ps1 build`): `PASS=903 WARN=118 ERROR=0 TOTAL=1021`, run with `--threads 2`: the first fix-round build (4 threads) was stopped by the machine running low on memory at step 531 (`int_page_cell`); with 2 threads it passed. First commit (7ca1b4f1):
`PASS=891 WARN=117 ERROR=0 TOTAL=1008`. CI fixture after fix round 1 (`ci/run_fixture_build.py`, local, new folder):
step 4 `PASS=3`; build `PASS=496 WARN=5 ERROR=0 TOTAL=501`; empty run `PASS=2`; unit-test and drift step `PASS=52`.

- Column tests (not_null, accepted_values) on the nine models; `tests/int_page_keys_unique.sql` (every key, and a row
  per position of `int_source_row`).
- Eight unit tests: cumulative columns and the rowspan rule (a deeper span flagged, a no-break space); the header
  forms and the title; the leaves of a two-line header; the column rules (a currency marker inside another column's
  zone moved to the number's column, a marker before text left alone, a trailing footnote mark, a row of the wrong
  width given no column); schedule boundaries (header change, first title, same title normalised, non-schedule table
  between); heading detection with runs (a run kept across a page break, broken by a schedule); headings by depth (the
  section kept behind sibling headings, no carry into the next schedule). The rowspan test was shown to fail with one
  expected column changed (first commit).
- Eight baselines with ceilings in `dbt_project.yml` (`baseline_max`): `int_page_position_not_placed` 0,
  `int_page_position_several_rows` 0, `int_page_cell_row_width` 31, `int_page_cell_deeper_span` 0,
  `int_page_table_no_header` 1, `int_page_position_no_column` 1, `int_page_field_split_columns` 35 (was 27),
  `int_page_field_fact_no_column` 36 (new).

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
| 5 | `int_page_column_filing` mixed tables | Re-keyed on (accession, table_signature, header_signature); shares exclude footnote marks; trailing footnote marks get the unheaded column `#footnote_marks` | Units 238 / 236 / 241 / 120 / 148 (Ares / BCRED / Blue Owl / Apollo / HPS). Unheaded footnote cells: Ares 19,952, Apollo 8,329; footnote marks still under a header: BCRED 22,238, Blue Owl 1,995, Apollo 2,509, HPS 2,399 |

How the depth inference behaves per fund (it assigns no meaning; these are checks, not rules):

- BCRED: runs of up to 3 (asset class, affiliation section, industry). 40 positions in one filing
  (0001803498-23-000021) keep "Equity (continued)" at depth 1 instead of "Equity - non-controlled/non-affiliated": the
  page-top continuation run repeats only two of the three levels, so depth counts from the bottom shift. An estimate
  (`scripts/text/q_p1_fix1_depth_upper.sql`: a lone heading between a position and its depth-1 heading whose text tops
  a longer run elsewhere) finds 133 BCRED positions where a lone "Structured Finance Obligations" heading shadows the
  depth-1 heading.
- Apollo: runs of 1 or 2 (industry over brand, or a brand alone). The same estimate finds 0 positions where a lone
  industry heading is shadowed; an industry is always followed by a brand in the filings seen. If Apollo ever prints an
  industry directly over a position with no brand, that industry would read as depth 0 and the next brand's depth 1
  would show the older industry. Structure cannot tell that case from a brand alone; Apollo's wrapper industry list
  (slice I) is the way to tell them apart.
- Blue Owl: runs of up to 3. The 2,271 positions printed in its unfunded-commitment tables sit under single headings
  ("Non-controlled/non-affiliated - debt commitments"), so they have depth 0 only. The estimate finds 0.
- Ares: only single industry headings (depth 0). HPS: runs of up to 3; the estimate finds 0.
- The reset condition (a deeper heading between) never removes a heading with runs defined this way: a run that holds
  a heading deeper than d also holds one at depth d nearer the position. It is kept as stated.

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
- Headings: nothing says which are industries, sections, issuers or brands. Depth is a structural count from the
  bottom of a run, not a level; section 5 lists where it is known to slip.
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