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
| `int_page_cell_column` | The leaf whose zone holds each data cell's first column; the cell's shape |
| `int_page_column_filing` | Per filing and signature: tables, data cells by shape, placed facts by concept. Counts only |
| `int_page_heading` | Heading rows: no facts, exactly one non-empty cell, below the header. Features `is_continued`, `next_row_kind`, `seen_in_prior_filing` |
| `int_position_heading` | The nearest 4 headings above each placed position, in document row order across page tables, with rank, distance and same-table flag |

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
| Placed positions (all) with no heading above | 0 | 0 | 0 | 0 | 0 |
| ... whose nearest heading is in another table | 17,413 | 2 | 5,561 | 2 | 2,996 |

Notes: Ares prints each industry heading once per filing, so most positions take it from an earlier page table.
Apollo's 751 distinct headings mix industries and issuer brands (as the spec, 4.1a, says). The P0 counts of
2026-11-25 (2,270 Blue Owl positions unplaced, 1 Ares in several rows) do not hold with the fact `int_field_read`
reads (section 6, item 1). The one table with no header: Ares 0001287750-23-000021, table 91, 28 rows, first position
on its 18th row, one published position (`baseline_int_page_position_no_column` 1).

The 31 rows whose width differs (all Blue Owl): 18 header rows of its width-54 tables (the header's colspans sum to
less than the data rows'), 12 "Total ..." rows and 1 section heading in its two-line-header tables. The P0 count of
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

## 4. Tests added

Build of record (2026-11-26, `.\warehouse\dbt.ps1 build`): `PASS=891 WARN=117 ERROR=0 TOTAL=1008` (this slice adds 63: 8 models, 40 column tests, the key test, 7 unit tests, 7 baselines). CI fixture (`ci/run_fixture_build.py`, local, new folder): step 4 `PASS=3`; build `PASS=484 WARN=5 ERROR=0
TOTAL=489`; empty run `PASS=2`; unit-test and drift step `PASS=51`.

- 40 column tests (not_null, accepted_values) on the eight models; `tests/int_page_keys_unique.sql` (every key, and a
  row per position of `int_source_row`).
- Seven unit tests: cumulative columns and the rowspan rule (including a deeper span flagged and a no-break space),
  the header forms, the leaves of a two-line header, "$" then number, heading detection, nearest heading carried
  across tables. The rowspan test was shown to fail with one expected column changed.
- Seven baselines with ceilings in `dbt_project.yml` (`baseline_max`): `int_page_position_not_placed` 0,
  `int_page_position_several_rows` 0, `int_page_cell_row_width` 31, `int_page_cell_deeper_span` 0,
  `int_page_table_no_header` 1, `int_page_position_no_column` 1, `int_page_field_split_columns` 27.

Field split (27 table-field pairs): HPS 23 (PIK rate 13, rate tag 7, spread 3), BCRED 2 (PIK rate 1, rate tag 1), Ares
2 (spread 2). Each case looked at prints the odd value in the neighbouring rate column, for example "13.75% PIK" in
"Reference Rate and Spread", or the coupon "12.55% (4.13% PIK)" carrying the spread tag under "Coupon". The columns
follow the print; the split is the filer's. Detail: `scripts/text/q_p1_split_detail.sql`.

## 5. What is not known

- Whether any cell sits in the right column on the printed page: no page was opened. The field-split test is the
  only cross-check (tags under one column per table), and it cannot see a column that is consistently wrong.
- Headings: nothing says which are industries, sections, issuers or brands, or their level. A heading row with one
  cell can also be a stray note or a footnote line inside a schedule table.
- Subtotal rows under a heading were not compared with the rows beneath (plan P4 check). Not built.
- The 13 total rows of one fund whose layout differs from the position rows: their cells are assigned to the column
  zones by naive columns and some land one column group to the left (for example a "$" and amount under "units"
  rather than "amortizedcost"). They are not position rows; no tagged position fact is affected (the split test
  reads position facts only).
- Tables without a header lose their cells' columns; one table today.
- The CI fixture has a schedule, but whether its page shape exercises every branch was not checked; the unit tests
  carry the logic.

## 6. Judgement calls

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
   Fair Value". A title above the whole table is excluded by the "not all cells" condition (seen on joint-venture
   tables).
7. Leaves: a lower-line cell under no upper cell is its own leaf with its own text as header (so "Company" reads the
   same in both two-line layouts); a header cell with no letter or digit (spacer "." cells of one fund) is ignored.
8. Zones: a data cell belongs to the leaf whose zone contains its first column; a zone runs to the next leaf, so
   columns under an empty header cell join the leaf on their left. This keeps "$" and "%" cells with their number.
9. Signatures: lower case, digits in brackets removed, white space removed; two-line leaves join with "/". Other
   footnote marks (letters, asterisks) are kept.
10. Shapes: added `footnote_mark` beside the brief's five (number, percent, date, text, empty_marker), because one
    fund prints footnote marks in the fair-value column zone.
11. Headings only in tables with a header; `next_row_kind` looks within the table and skips rows with no text;
    `end_of_table` is a fourth value. `seen_in_prior_filing` compares exact text with the fund's previous filing here.
12. `int_position_heading` carries headings across any table of the filing that lies between (only schedule tables
    hold headings).
