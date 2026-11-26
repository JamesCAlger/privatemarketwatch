# Baseline: rate text, slice R phase 1 (2026-11-26)

Branch `warehouse-text-spec`. Plan: `docs/2026-11-26-text-plan.md`, slice R, tasks R1 and R2 and the checks R4/R5 need.
Phase 1 is code only: no model call, no agent, no network. Queries: `scripts/text/q_r2_*.sql` to `q_r6_*.sql`.

**No page was read by a person. Agreement with production is not correctness. Nothing here applies a new rule:** the
only rules applied are the ones the wrapper copies already hold (19-T7). Every count is a measurement of the filed
layer and the page models.

## 1. What each model decides

| Model | Decides |
|---|---|
| `int_text_cell` | The text of each leaf column on each printed position row: the column's cells joined by a space in cell order, footnote marks left out. Its shape (numbers become `#`), leading code, whether it looks like rate text, and the fields of the facts placed in it |
| `int_text_column_unit` | Column units across filings, one row per (cik, table signature, column signature): header and group header, dates, filings, tables, shape shares, position-row cells, tag profile, the `read_printed_column` rules naming it, and `is_rate_candidate` |
| `int_text_shape_unit` | Text shapes within each rate-candidate column: texts, positions, dates, 3 examples, code, facts per field |
| `int_text_reference_rate_read` | The existing reference-rate rules applied to every position with a printed row: cell text, code, reference rate, rule ids, status |
| `int_text_check_column_tags` | Per column unit: the field the filer's tags say it holds (dominant field and share), and untagged rows |
| `int_text_check_legend` | The filer's own definitions of rate codes in footnotes (one general pattern) |
| `int_text_check_legend_rule` | Per existing `map_code` rule: agrees, contradicts, mixed, unclear or not_in_legend |
| `int_text_check_legend_code` | Per (fund, code) printed in rate-candidate columns: rule, legend, both or neither |
| `int_text_check_spread_base` | Per position with a code: tag spread plus SOFR (or the printed floor when higher) against the all-in rate |
| `int_text_check_spread_base_unit` | The same per (column unit, quarter, code) |
| `int_text_check_shape_legs` | Per parts-stating shape: which printed number equals which tagged leg on the same row |
| `int_text_worklist` | Per column unit and shape unit: covered, covered_unchecked, failed_check, uncovered; `changed_state` null (not built) |
| `int_text_bundle` | Per rate-candidate column unit: the JSON bundle an agent gets (spec 4.3) |

Seed `sofr_90day_avg`: a copy of `data/reference/sofr_90day_avg.csv` (the file `pipeline/sofr_reference.py` reads), sha256
of the committed bytes recorded in `seeds/_seeds.yml`. No network.

Rules written into the model headers:

- Rate-candidate column: (a) a fact read as spread, interest rate, cash rate or PIK rate is placed in it on a position
  row; or (b) an existing `read_printed_column` rule names it (header signature, or the sub-header's signature for a
  two-line leaf); or (c) at least 20% of its non-empty position-row texts look like rate text (a number followed by `%`,
  or letters followed by `+`).
- Shape: every number (digits, thousands groups, decimals) becomes `#`, white space collapsed, letters kept. A code that
  is the letter N stays `N` (`N+475` gives `N+#`).
- Code: the leading word or words of letters, ended by `+`, `(`, a digit or the end (`SOFR (Q)` gives `SOFR`,
  `Base Rate (Q)` gives `Base Rate`, `N/A` gives none).

## 2. Units and worklist per fund

All parsed filings of the five funds (as slice P). Worklist states over all column units; shapes exist only in
rate-candidate columns.

| | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| Column units | 14 | 64 | 43 | 16 | 12 |
| Rate-candidate columns | 3 | 14 | 10 | 2 | 2 |
| by (a) rate tags / (b) named by a rule / (c) rate text | 2 / 1 / 2 | 14 / 7 / 14 | 6 / 4 / 10 | 2 / 2 / 2 | 2 / 1 / 2 |
| Shape units | 46 | 98 | 59 | 68 | 36 |
| Most shapes in one column | 39 | 14 | 31 | 45 | 32 |
| Columns covered / covered_unchecked / failed_check / uncovered | 0 / 1 / 0 / 13 | 1 / 0 / 6 / 57 | 1 / 0 / 3 / 39 | 2 / 0 / 0 / 14 | 0 / 0 / 1 / 11 |
| Shapes covered / covered_unchecked / failed_check / uncovered | 0 / 17 / 0 / 29 | 29 / 0 / 6 / 63 | 14 / 1 / 4 / 40 | 6 / 0 / 0 / 62 | 10 / 0 / 4 / 22 |

- No shape explosion. The largest counts (Apollo 45, Ares 39) are one column each. Apollo's "Interest Rate" prints a
  code, a spread in basis points, a floor and PIK wording in one cell (`S+#, #% Floor`, `S+# Cash plus #% PIK, #% Floor`,
  `S+# (includes #% PIK)`, ...). Ares's "Reference" prints a rate name and a reset frequency (`SOFR (Q)`, `SOFR (M)`,
  `LIBOR (S)`, `Base Rate (Q)`, ...), and each name and frequency pair is its own shape.
- Rate-candidate columns by signature (`scripts/text/q_r4_measure_column_tags.sql`): Ares coupon, reference, spread;
  BCRED interestrate and referencerateandspread (7 table kinds each); Blue Owl interest, interest/ref.rate,
  interest/cash, interest/pik and its two share-of-net-assets columns (rule (c) false positives: "1.25%"); Apollo
  interestrate (2); HPS interestrate and referencerateandspread.
- The tag check (`int_text_check_column_tags`) on those: every tagged rate column has a dominant field at 0.90 or more
  (Ares coupon interest rate 0.90, the rest 0.94 to 1.00). The reference columns (Ares 13,657 rows, Blue Owl ref.rate
  3,643) carry no tag at all. Untagged rows in tagged columns: BCRED referencerateandspread 214 ("Estimated Yield:"),
  Blue Owl interest 332 ("N/A"), Apollo 259.
- "covered" for a column only means an existing rule names it and no check found a fault. Inside a covered column most
  shapes are uncovered, because no rule maps their code (section 3).

## 3. Existing rules applied: reference-rate read status (published positions)

| Status | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| read | 541 | 613 | 3,509 | 63 | 452 |
| code_not_mapped | 13,116 | 13,283 | 3,749 | 7,329 | 5,960 |
| no_code | 0 | 537 | 998 | 636 | 162 |
| cell_empty | 7,533 | 1,098 | 0 | 6 | 1,868 |
| column_not_found | 1 | 0 | 2,271 | 0 | 0 |
| no_rule | 0 | 0 | 0 | 0 | 0 |

- `code_not_mapped` is the agent's work, not an error. The wrappers list only the codes production's global fallback
  does not know, and no global vocabulary is copied here, so the common codes stay unread: Ares `SOFR` 11,359 rows,
  `LIBOR` 1,308; BCRED `SOFR` 18,683, `L` 2,584, `E` 632; Blue Owl `S` 3,388 (the post-2025 "Ref. Rate" column; the older
  `SR` is mapped); Apollo `S` 6,372, `E` 407, `SONIA` 361; HPS `SF` 5,442, `E` 403 (rows of all positions, published or
  not; `int_text_check_legend_code`).
- `column_not_found`: Blue Owl's 2,271 unfunded-commitment-only positions (no rate column in that table) and Ares's one
  table without a header. `cell_empty`: non-loan rows (equity) where the column prints nothing.
- `no_code`: "N/A", a fixed rate printed in the reference column, BCRED "Estimated Yield:".
- No position matched two named columns; no code matched two `map_code` rules at one date.

## 4. Legend check

The legend pattern found rate definitions in the filings of BCRED, Blue Owl, Apollo and HPS, and none in Ares's (its
footnotes print no quoted codes).

`map_code` rules (32): agrees 20, mixed 4, unclear 1 (BCRED F=FEDFUNDS: "Federal Funds Rate ("F")" prints no
abbreviation), not_in_legend 7 (Ares's 5, Blue Owl BB=BBSY and its dated C=CDOR), contradicts 0.

Every mixed rule, where the filer defines the code two ways in one filing (`scripts/text/q_r4_legend_mixed.sql`):

| Fund | Rule | Filing (report date) | Legend entries for the code |
|---|---|---|---|
| BCRED | S=SONIA | 0001803498-23-000008 (2022-12-31) | "Sterling Overnight Interbank Average Rate (SONIA or S)" and "Secured Overnight Financing Rate (SOFR or S)". Its other 14 filings define S as SONIA only |
| Blue Owl | C=CORRA (from 2024-06-30) | 0001812554-25-000009 (2024-12-31) | C as CDOR and as CORRA |
| HPS | B=BBSY | 0001838126-25-000017 (2024-12-31) | B as BBSY and as BBSW |
| HPS | C=CORRA (from 2025-06-30) | 0001838126-25-000055, 0001838126-25-000073, 0001628280-26-020206 (2025-06-30 to 2025-12-31) | C as CDOR and as CORRA |

The three CDOR/CORRA and BBSW/BBSY cases look like transition legends: the filer keeps the old definition while old
loans run off. The BCRED case is one filing. The legend alone cannot tell whether BCRED's 372 "S +" rows are SONIA or
SOFR, and the spread check cannot either (SONIA and SOFR were within 0.25 of each other in most quarters; section 5).

Codes printed in rate-candidate columns with neither a rule nor a legend entry (12; baseline):

| Fund | Code (rows) |
|---|---|
| Ares | SOFR (11,359), LIBOR (1,308), EURIBOR/Euribor (172), CORRA (144), SONIA (131), "CAD Base Rate" (2) |
| BCRED | SORF (1, a typo for SOFR) |
| Blue Owl | L (278) |
| Apollo | SONIA (361), "Equity plus" (5), N (4), "Variable" (2) |

Codes with a legend entry and no rule (the agent's starting point; legend abbreviation in brackets): BCRED E (Euribor),
L (LIBOR), P (none printed), SOFR; Blue Owl E, P, S (SOFR); Apollo E, K (KORIBOR), L, NIBOR, P, S (SOFR), SARON, STIBOR,
T (TONAR, and once MUTKCALM, "Japan Unsecured Overnight Call Rate Expected"); HPS BB (BKBM), BS, E, L, P, SF (SOFR).

## 5. Spread plus base rate (SOFR only)

Rows that an existing rule reads as SOFR exist only at Blue Owl (`SR`, 4,750 rows), and Blue Owl has no all-in rate tag.
So the check as briefed judged **no row**. Apollo has no all-in tag either. The model keeps every code, so the same check
was also measured for codes no rule maps yet, as if they were read as SOFR (`int_text_check_spread_base_unit`;
`scripts/text/q_r4_measure_spread_base.sql`). Pass share = the share of rows within 0.25 of tag spread + SOFR 90-day
average. The floor is used only where the read cell prints it; none of these three funds prints it there. Loans with
PIK are not judged.

| Quarter | Ares `SOFR` | BCRED `SOFR` | HPS `SF` |
|---|---:|---:|---:|
| 2022-09-30 | 0.06 (88) | 0.05 (215) | |
| 2022-12-31 | 0.06 (226) | 0.06 (296) | |
| 2023-03-31 | 0.13 (242) | 0.13 (485) | 0.10 (147) |
| 2023-06-30 | 0.54 (551) | 0.64 (818) | 0.71 (207) |
| 2023-09-30 | 0.58 (585) | 0.78 (1,109) | 0.73 (256) |
| 2023-12-31 | 0.93 (625) | 0.85 (1,147) | 0.91 (279) |
| 2024-03-31 | 0.98 (635) | 0.99 (1,114) | 0.98 (276) |
| 2024-06-30 | 0.99 (664) | 0.97 (1,192) | 0.97 (301) |
| 2024-09-30 | 0.34 (653) | 0.42 (1,234) | 0.39 (318) |
| 2024-12-31 | 0.54 (668) | 0.51 (1,330) | 0.46 (380) |
| 2025-03-31 | 1.00 (693) | 0.94 (1,367) | 1.00 (419) |
| 2025-06-30 | 1.00 (720) | 1.00 (1,438) | 1.00 (456) |
| 2025-09-30 | 0.75 (731) | 0.80 (1,491) | 0.76 (466) |
| 2025-12-31 | 0.48 (751) | 0.40 (1,585) | 0.40 (471) |
| 2026-03-31 | 0.98 (754) | 0.97 (1,586) | 0.99 (469) |

Checked rows in brackets. 2026-06-30 and 2026-09-30 have no SOFR value within 7 days (the seed ends 2026-06-18).

What this shows: **the check fails in quarters when SOFR moved, whatever the code.** It passes at 0.93 to 1.00 when
SOFR was steady for three months (2024 H1, 2025 H1, 2026-03-31). It fails when the Fed was moving: the 2022-2023 hikes,
the cuts of September and December 2024, and those of September to December 2025. The 90-day backward average lags the
term SOFR the loans reset to, and in 2022 unprinted floors above SOFR add to the gap. Under the plan's rule that every
quarter passes on its own, this check would reject a correct SOFR rule in 7 of 15 quarters. Before it can accept a rule
it needs a spot or term SOFR series (not in the repository; no network was used) or a wider tolerance, measured, for
moving quarters. Other codes, as if SOFR: BCRED `S` also passes 0.93 to 1.00 in steady quarters, which does not tell SOFR
from SONIA. `E`, `L`, `CA`, `SA` and `ST` fail, as they should (0.00 to 0.12 overall).

## 6. Shape legs (evidence, not a verdict)

`int_text_check_shape_legs`, `scripts/text/q_r4_measure_legs.sql`. In every parts-stating shape with 5 or more rows:

- Ares `#% (#% PIK)` (1,262 rows), BCRED `#% (incl. #% PIK)` (all 7 table kinds), Apollo `#% (includes #% PIK)`: on every
  compared row the first number equals the tagged all-in rate and the second the PIK rate. Their sum equals neither.
  So the first number is the all-in rate including PIK.
- HPS `SF + #% (incl #% PIK)` (364 rows) and its E, SN, L, N, SORA and ST forms: on every row the first number equals the
  tagged spread and the second the PIK rate. The spread includes the PIK part.
- Blue Owl `SR + #% (#% PIK)` (117 rows) and its S, E and L forms: the second number equals the PIK rate on every row. The
  first equals the spread tag on the 6 rows that have one.
- Apollo `S+# Cash plus #% PIK, #% Floor` (62 and 35 rows), `SONIA+# Cash plus #% PIK, ...` and `S+# (includes #% PIK)`:
  the second number equals the PIK rate on every row. The first (in basis points) rarely meets a spread tag (equal as
  basis points on 2 to 4 rows), so the tags cannot tell which spread it is.

## 7. Bundles

31 bundles, one per rate-candidate column unit: Ares 3, BCRED 14, Blue Owl 10, Apollo 2, HPS 2. They run from 1,849 to
6,113 characters, 121,135 bytes in all. `scripts/text/export_bundles.py` wrote them to
`scratch/2026-11-26_text_slice_r/bundles/` (31 files plus `_manifest.tsv`). Determinism: exported once after a partial
build and again after the full build that rebuilt every model; the 31 sha256 values are identical.

Caps, recorded inside each bundle: the 12 most frequent cells, 40 shapes, 3 example rows, every text cut to 200
characters. One bundle reaches the shape cap: Apollo's larger "Interest Rate" unit (45 shapes; `shapes_total` records
45). By worklist state: uncovered 16, failed_check 10, covered 4, covered_unchecked 1. Each bundle carries the group
header with a sub-header and the other cells of the example rows (class C of the stability note). Numbers are not
masked.

## 8. Agreement with production (MEASUREMENT ONLY)

`scripts/text/q_r5_vs_production.sql`: the rule-read reference rate against production's `reference_rate_type`, on
published positions both sides hold. **Agreement with production is not correctness.** The rule-read side applies only
the existing rules.

| | Ares | BCRED | Blue Owl | Apollo | HPS |
|---|---:|---:|---:|---:|---:|
| same | 137 | 613 | 3,494 | 48 | 452 |
| production only | 12,250 | 13,283 | 3,354 | 6,631 | 5,960 |
| new only | 379 | 0 | 0 | 0 | 0 |
| both empty | 7,003 | 1,603 | 2,867 | 569 | 2,030 |
| differ | 0 | 0 | 4 | 0 | 0 |

Differences grouped:

- production only: the unmapped common codes (section 3), which production reads with its global fallback. Among them,
  production holds SOFR on rows whose code the filer's legend defines otherwise: Apollo K 9 (KORIBOR), T 6 (TONAR),
  N 4 (Apollo's legend defines NIBOR as "NOK", not "N"); HPS BS 6 and BB 2 (legend: Bloomberg Short Term Bank Yield
  Index, BKBM), and HPS BS 2 as LIBOR. The Apollo rows repeat the production errors of the stability note; the HPS rows
  are new.
- new only: Ares "Base Rate" / "Base rate", 379 rows, read as `unspecified` by the wrapper's label_is_unspecified rule.
  Production leaves them blank.
- differ: 4 Blue Owl rows print "SR +" where production holds LIBOR.

## 9. Tests and build

- New: 13 rate-text models and the seed `sofr_90day_avg`; macros `text_shape`, `rate_code`, `is_rate_text` and
  `text_numbers` (`macros/text_rate.sql`).
- Column tests in `_intermediate.yml`. Keys and coverage in `tests/int_text_keys_unique.sql`, which also checks that
  every position with a printed row has a read row and that `changed_state` is always null.
- Six unit tests: shape masking with the letter-N code and split cells; the rate-candidate rule at the 20% boundary;
  legend parsing on three real forms, with curly quotes and an excluded "(GAAP)"; the legend rule states; the read
  statuses with dated rules and a sub-header rule; the spread-base arithmetic (pass, fail, floor, tolerance edge, PIK,
  missing input, stale SOFR). The shape test failed on its first run: the number pattern swallowed the comma in
  "S+525, 0.50% Floor". It was fixed before any measurement in this note; the shape counts above are after the fix.
- Four baselines with measured ceilings (`baseline_max`): `int_text_reference_rate_column_not_found` 2,272,
  `int_text_reference_rate_code_not_mapped` 43,437, `int_text_legend_rule_disagrees` 4,
  `int_text_code_no_rule_no_legend` 12.
- Full build (`.\warehouse\dbt.ps1 build --threads 2`): `PASS=973 WARN=123 ERROR=0 TOTAL=1096`. The 4 new warnings are the
  four baselines. CI fixture (`ci/run_fixture_build.py`, run locally into a new folder): step 4 `PASS=3`; build
  `PASS=566 WARN=5 ERROR=0 TOTAL=571`; empty run `PASS=2`; unit-test and drift step `PASS=58`.

## 10. Not known

- Whether any reading is right on the printed page: no page was opened.
- Whether BCRED's "S" is SONIA (the rule) or SOFR (one 2022-12-31 footnote).
- How strong the spread check really is: section 5 shows the SOFR proxy failing in moving quarters, whatever the rule.
- The "changed" state (spec 4.2) is not built.

## 11. Judgement calls and deviations from the brief

1. Cell text = the column's cells on the row joined, not one cell, because the filers print "SOFR +" and "5.25%" in two
   cells under one header. A new helper model, `int_text_cell`, holds it (a cleaner split: every later model reads the
   same text).
2. Status `no_code` added to the five briefed statuses: a cell with text but no leading code ("N/A", "10.00%") is
   neither empty nor an unmapped code.
3. No global vocabulary: only a rule of the fund reads a code, so 'SOFR' itself is unmapped where no rule lists it.
4. `label_is_unspecified` gives reference_rate `unspecified`.
5. The legend check is split into three models (entries, per rule, per code) because it has three grains. A fourth rule
   state, `mixed`, was added (the code defined two ways in one filing); the worklist counts mixed and contradicts as a
   failed check.
6. Spread-base: the spread is the tag only (no existing rule reads a spread from text); the floor is used only when the
   read cell prints it; PIK rows are not judged; SOFR older than 7 days is not used. Rows of every code are kept, and
   `is_read_sofr` marks the briefed subset. A per-(unit, quarter, code) summary model was added. Worklist thresholds:
   quarters with 10 or more checked rows, pass share 0.90 (vars).
7. Rate-candidate rule (c) is applied to the joined texts. It admits share-of-net-assets columns.
8. Bundle: the header row comes from the latest table; the title is the most frequent title among the unit's tables;
   the tag profile and the legend cover all filings; shapes are capped at 40.
9. The seed's sha256 is recorded twice: for the committed bytes (LF) and for the Windows checkout (CRLF).
   `.gitattributes` (outside `warehouse/`) was not changed.
