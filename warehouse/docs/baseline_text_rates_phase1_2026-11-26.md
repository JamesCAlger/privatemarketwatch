# Baseline: rate text, slice R phase 1 (2026-11-26)

Branch `warehouse-text-spec`. Plan: `docs/2026-11-26-text-plan.md`, slice R, tasks R1 and R2 and the checks R4/R5 need.
Phase 1 is code only: no model call, no agent, no network. Queries: `scripts/text/q_r2_*.sql` to `q_r6_*.sql`.

**No page was read by a person. Agreement with production is not correctness. Nothing here applies a new rule:** the
only rules applied are the ones the wrapper copies already hold (19-T7). Every count is a measurement of the filed
layer and the page models.

**Fix round 1 (independent review of 0f243ca7) changed the worklist, the legend check, the rate check, the bundles and
the shapes. Section 12 has what changed with before/after numbers per fund; where sections 1 to 11 disagree with
section 12, section 12 holds. Fix round 2 (review of 9285a8ad) took the cluster test out of every verdict: section 13
holds over section 12.** **There is at present no arithmetic check on the reference rate or the spread** (section
13.1). Bundles are not anonymous: the table title (16 of 31 bundles), company names and
filing accessions name the fund. They carry no production value.

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
   `.gitattributes` (outside `warehouse/`) was not changed. (Superseded in fix round 1, item 7.)

## 12. Fix round 1 (independent review of 0f243ca7, 2026-11-26)

Queries: the reviewer's `scripts/text/review_r1_*.sql` and `scripts/text/q_r7_*.sql`. All counts below are from the
fix-round build.

### 12.1 What changed

| # | Finding | Change |
|---|---|---|
| 1 | A column was `covered` when one minor rule passed (Apollo "Interest Rate" read 17 of 4,916) | `int_text_worklist` carries rows_in_unit (positions), rows_read, rows_read_by_passing_rule, rows_read_failing and both shares on every row. `covered` needs at least 95% of the unit's positions read by rules that pass a check in their own quarter (var `text_covered_min_share`); new state `partly_covered`; `covered_unchecked` = 95% read, not confirmed. Unit test `int_text_worklist_states`. The export writes every rate-candidate column by default |
| 2 | The legend check was not dated | New `int_text_check_legend_read`: each read position against the legend of its own filing (agrees, contradicts, mixed, unclear, no_legend_in_filing; not_applicable for label_is_unspecified). `int_text_check_legend_quarter` counts them per unit and quarter; the worklist lists the quarters. `int_text_check_legend_rule` now judges every filing of the rule's dates and lists the report dates per verdict. Unit tests `int_text_check_legend_rule_states` (rewritten) and `int_text_check_legend_read_verdicts` |
| 3 | The SOFR level test accepted nothing and would fail a correct rule in 7 of 15 quarters | Renamed `int_text_measure_sofr_level(_unit)`, measurement only, read by nothing. New cluster test `int_text_check_base_cluster` (rows) and `int_text_check_base_cluster_group` (fund, quarter, basis, label), read by the worklist for basis `rule`. Unit test `int_text_check_base_cluster_group_centres` |
| 4 | Bundles lacked what a dated rule needs | First and last report date on the column and on every shape; every legend entry lists its filings (report date, accession); shape-legs evidence on each parts-stating shape; header_text, group header and header row from the same (latest) table. The header's printed note: not done, see 12.6 |
| 5 | The model comment said bundles name no fund | Comment and this note corrected: bundles are not anonymous (the title names the fund in 16 of 31), they carry no production value |
| 6 | Shapes split by spacing and case (307 shapes) | Macro `text_shape` drops the space before `%` and around `+`; shape units group on the upper-case key (`text_shape_key`) and show the most frequent spelling. 286 shape units. Unit tests `int_text_cell_shape_and_code` (extended) and `int_text_shape_unit_key_and_display` |
| 7 | The seed's sha256 was only in a description | `tests/seed_sofr_hash_matches.sql` hashes the file (CRLF read as LF, as `stg_wrapper_drift` does) against var `sofr_seed_sha256`; `warehouse/seeds/sofr_90day_avg.csv -text` in `.gitattributes` (the file re-checked-out with its committed bytes) |
| 8 | Checks and bundle read `int_field_corrected`, which reaches `stg_holdings` | Every `int_text_*` model reads `int_field_normalised` (tags converted, before corrections). `pytests/test_text_models_no_production.py` walks the ref graph from the SQL files and macros and fails if an `int_text_*` model has `stg_holdings` or a `cmp_*` model among its ancestors (a guard test checks the walker sees `cmp_rate -> stg_holdings`) |

Also fixed: the header of `tests/baseline_int_text_code_no_rule_no_legend.sql` named the funds, which
`pytests/test_no_fund_names_in_sql.py` forbids; the first commit did not run that test. Now passes.

### 12.2 Worklist before and after

Columns: covered / covered_unchecked / partly_covered / failed_check / uncovered.

| Fund | Before (no partly_covered state) | After |
|---|---|---|
| Ares | 0 / 1 / - / 0 / 13 | 0 / 0 / 1 / 0 / 13 |
| BCRED | 1 / 0 / - / 6 / 57 | 0 / 0 / 5 / 2 / 57 |
| Blue Owl | 1 / 0 / - / 3 / 39 | 0 / 0 / 3 / 1 / 39 |
| Apollo | 2 / 0 / - / 0 / 14 | 0 / 0 / 2 / 0 / 14 |
| HPS | 0 / 0 / - / 1 / 11 | 0 / 0 / 0 / 1 / 11 |

Shapes, covered / covered_unchecked / failed_check / uncovered (no shape is partly covered): Ares 0/17/0/29 -> 3/12/0/27;
BCRED 29/0/6/63 -> 31/1/2/61; Blue Owl 14/1/4/40 -> 7/8/1/33; Apollo 6/0/0/62 -> 4/2/0/59; HPS 10/0/4/22 -> 12/0/2/21.

**No column is covered.** Every column a rule names, with its shares (positions; `scripts/text/q_r7_worklist.sql`):

| Fund | Column [unit] | State | In unit | Read | By passing rule | Failing | Share read / passing | Failing quarters |
|---|---|---|---:|---:|---:|---:|---|---|
| Ares | Reference [9ecddf] | partly_covered | 13,657 | 541 | 421 | 0 | 0.040 / 0.031 | |
| BCRED | Reference Rate and Spread [16de07] | partly_covered | 3,901 | 13 | 13 | 0 | 0.003 / 0.003 | |
| BCRED | Reference Rate and Spread [35d86f] | partly_covered | 6,200 | 154 | 154 | 0 | 0.025 / 0.025 | |
| BCRED | Reference Rate and Spread [d242ee] | partly_covered | 555 | 3 | 3 | 0 | 0.005 / 0.005 | |
| BCRED | Reference Rate and Spread [d30801] | partly_covered | 9,169 | 407 | 407 | 0 | 0.044 / 0.044 | |
| BCRED | Reference Rate and Spread [4911ba] | partly_covered | 971 | 1 | 1 | 0 | 0.001 / 0.001 | |
| BCRED | Reference Rate and Spread [7bedc6] | failed_check | 1,229 | 30 | 17 | 13 | 0.024 / 0.014 | 2023-03-31 |
| BCRED | Reference Rate and Spread [fc9493] | failed_check | 1,342 | 41 | 13 | 22 | 0.031 / 0.010 | 2022-09-30, 2022-12-31 |
| Blue Owl | Interest / Ref. Rate [501a2d] | partly_covered | 2,109 | 29 | 29 | 0 | 0.014 / 0.014 | |
| Blue Owl | Interest / Ref. Rate [aceeb6] | partly_covered | 1,534 | 29 | 29 | 0 | 0.019 / 0.019 | |
| Blue Owl | Interest [0dd66c] | partly_covered | 1,416 | 1,343 | 0 | 0 | 0.948 / 0.000 | |
| Blue Owl | Interest [256066] | failed_check | 4,613 | 3,451 | 5 | 2 | 0.748 / 0.001 | 2024-12-31 |
| Apollo | Interest Rate [b4ee19] | partly_covered | 4,916 | 17 | 10 | 0 | 0.003 / 0.002 | |
| Apollo | Interest Rate [8900b6] | partly_covered | 3,112 | 46 | 46 | 0 | 0.015 / 0.015 | |
| HPS | Reference Rate and Spread [836097] | failed_check | 6,662 | 452 | 434 | 18 | 0.068 / 0.065 | 2024-12-31, 2025-06-30, 2025-09-30, 2025-12-31 |

Blue Owl's `SR` reads (3,451 + 1,343) are almost all unchecked: the fund files no all-in rate, so the cluster test
cannot run, and its legend defines SR only in the 2024-12-31 filing (SR=SOFR: agree 1 filing, no legend 14).

### 12.3 Legend, dated

Read positions by the verdict of their own filing (`int_text_check_legend_quarter`; `scripts/text/q_r7_legend_dated.sql`):

| Fund | Read | Agrees | Mixed | Contradicts | Unclear | No legend in filing | Not applicable | Quarters mixed |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Ares | 541 | 0 | 0 | 0 | 0 | 144 | 397 | |
| BCRED | 649 | 621 | 12 | 0 | 0 | 16 | 0 | 2022-12-31 |
| Blue Owl | 4,852 | 63 | 2 | 0 | 0 | 4,787 | 0 | 2024-12-31 |
| Apollo | 63 | 56 | 0 | 0 | 0 | 7 | 0 | |
| HPS | 452 | 434 | 18 | 0 | 0 | 0 | 0 | 2024-12-31, 2025-06-30, 2025-09-30, 2025-12-31 |

Before, one 2022-12-31 footnote failed five BCRED units for 2023 to 2026 and a 2024-12-31 legend failed Blue Owl's 2026
unit; now only the positions of the mixed filing's own quarter fail. Per rule (filings agreeing / mixed / no legend):
BCRED S=SONIA 14 / 1 (2022-12-31) / 1; Blue Owl SR=SOFR 1 (2024-12-31) / 0 / 14, C=CORRA 7 / 1 (2024-12-31) / 2,
B=BBSY and SA=SONIA 8 / 0 / 7; HPS B=BBSY 6 / 1 (2024-12-31) / 0, C=CORRA 2 / 3 (2025-06-30 to 2025-12-31) / 0;
Apollo BBSW 7 / 0 / 8, C=CORRA 6 / 0 / 9; Ares's 5 rules no legend in any of 17 filings. Contradictions: 0.

### 12.4 Cluster test

Implied base = tagged all-in rate minus tagged spread (tags before corrections), per fund, quarter and label; rows with
a PIK rate above 0 are left out (whether the spread includes the PIK leg differs by fund, so no cash leg is derived;
4% to 8% of coded rows at Ares, BCRED and HPS). Centres: the three most frequent implied bases rounded to 0.05. Within: the share of rows within
0.30 of the nearest centre. Full table `scratch/2026-11-26_text_slice_r/cluster.tsv` (`scripts/text/q_r7_cluster.sql`).

Distribution first, groups with at least 10 usable rows (`scripts/text/q_r7_cluster_bar.sql`):

| Basis | Groups | Median within | Below 0.80 | Below 0.85 | Below 0.90 | Below 0.95 | SOFR distance over 1.0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| rule (codes read by existing rules) | 49 | 1.000 | 1 | 2 | 2 | 3 | 15 (not SOFR: SONIA, CORRA, Prime-like "unspecified") |
| hypothesis, SOFR-like codes | 63 | 0.993 | 3 | 7 | 8 | 10 | 2 |
| hypothesis, other codes | 99 | 1.000 | 3 | 5 | 9 | 19 | 59 (expected: not SOFR) |

SOFR-like codes as hypothesis (within share, usable rows): Ares `SOFR`, BCRED `SOFR`, HPS `SF` are at 0.95 to 1.00 in
every quarter from 2023-03-31 on except 2024-09-30 (Ares 0.847, HPS 0.791; BCRED 0.985), and fall to 0.71 to 0.90 in
2022-09-30 and 2022-12-31. Main centre against the SOFR seed: within 0.5 from 2023-06-30 on in every quarter (0.00 to
0.46); above 1.0 only for Ares 2022-09-30 (1.57) and 2022-12-31 (1.13), when the 90-day average lagged the hikes.

Proposed bar (set in vars, `text_cluster_min_rows` 10, `text_cluster_min_share` 0.90): it fails these groups
(`scripts/text/q_r7_cluster_fails.sql`), all in quarters when rates moved fast inside the quarter (2022 hikes, the
2024-09 cut), where loans reset on different days and the implied bases spread over more than three tenors:

- rule basis: BCRED SONIA 2022-09-30 (0.70), 2023-03-31 (0.85).
- hypothesis: Ares SOFR 2022-09-30 (0.83), 2022-12-31 (0.90 rounded, 0.898), 2024-09-30 (0.85); BCRED SOFR 2022-09-30
  (0.71), 2022-12-31 (0.80); HPS SF 2024-09-30 (0.79); Ares LIBOR 2022-09-30 (0.78); BCRED L 2022-09-30, 2022-12-31
  (0.89, 0.88); E groups of BCRED and HPS (0.79 to 0.87) and Ares CORRA 2024-12-31 (0.77).

A bar of 0.95 would also fail 2024-12-31 for the three large SOFR groups (0.955 to 0.966); 0.85 would pass Ares SOFR 2022-12-31 and both BCRED L 2022 groups.
0.90 is the lowest round bar that still fails the 2022 quarters of the two largest SOFR groups.

What the cluster test cannot do: it shows that one code behaves like one base rate in a quarter, not which rate.
A code mapped to the wrong rate clusters just as well (BCRED's `S` clusters within 0.20 of SOFR whether it is SONIA or
SOFR: its main centre is 0.01 to 0.43 from the SOFR seed, and SONIA was close to SOFR in most quarters). The SOFR distance is the only link to a level, and it is a measurement.
Funds it cannot cover: Blue Owl (no all-in rate tag at all: no implied base) and Apollo (both tags on 0.1% of its
7,392 coded positions: every group too_few_rows).

### 12.5 Bundles

31 bundles (unchanged: one per rate-candidate column unit, all exported by default), 2,979 to 20,142 characters, about
228,200 characters in all (legend filing lists and shape dates made them larger). By state: partly_covered 11,
failed_check 4, uncovered 16. Exported to `scratch/2026-11-26_text_slice_r/bundles/`; determinism checked by exporting
before and after the full build (identical sha256 values; 12.7).

Left as they are, noted: one column printed under several table signatures gives several bundles (BCRED 7, Apollo 2);
the controller sends each and compares the answers. Share-of-net-assets columns are admitted by the 20% rate-text rule.

### 12.6 Not done

- The printed note a header's mark refers to ("Reference Rate and Spread(2)" -> note (2)). The filed layer stores
  table rows only; no table row of any filing starts with a mark "(n)" followed by text: 0 of 348 marks in rate-column
  headers found (`scripts/text/q_r7_note_rows.sql`, `q_r7_note_rows2.sql`). Left out of the bundle, said in its header.
- The old tables `int_text_check_spread_base(_unit)` stay in the local database file until it is rebuilt from empty;
  nothing reads them.

### 12.7 Tests and build (fix round 1)

New tests: unit tests `int_text_check_legend_read_verdicts`, `int_text_worklist_states`,
`int_text_shape_unit_key_and_display`, `int_text_check_base_cluster_group_centres`; rewritten
`int_text_check_legend_rule_states`; extended `int_text_cell_shape_and_code`; renamed
`int_text_measure_sofr_level_arithmetic`. `tests/seed_sofr_hash_matches.sql`; keys of the four new models in
`tests/int_text_keys_unique.sql`; `pytests/test_text_models_no_production.py` (3 tests). Baseline ceilings unchanged
(measured again: 2,272 / 43,437 / 4 / 12).

Full build (`dbt.ps1 build --threads 2`): `PASS=996 WARN=123 ERROR=0 TOTAL=1119` (was 973/123/1096). CI fixture
(local, new folder): step 4 `PASS=3`; build `PASS=589 WARN=5 ERROR=0 TOTAL=594`; empty run `PASS=2`; unit-test and drift
step `PASS=62`. pytests: 178 passed. Bundles: exported after the full build and again after rebuilding every text
model; the 31 sha256 values are identical.

## 13. Fix round 2 (review of 9285a8ad, 2026-11-26)

Reviewer queries: `scripts/text/review_r2_*.sql` (not committed). Queries of this round: `scripts/text/q_r8_*.sql`.

### 13.1 No arithmetic check on the reference rate or the spread

**There is at present no arithmetic check on the reference rate or the spread.** Both attempts failed:

- Spread plus the SOFR 90-day average against the all-in rate (`int_text_measure_sofr_level`): the 90-day backward
  average lags the term rate the loans reset to, so correct SOFR readings fail in every quarter when SOFR moved (7 of
  15; section 5).
- Clusters of all-in minus spread (`int_text_measure_implied_base`, `_group`, renamed from `int_text_check_base_cluster`
  in this round): the reviewer showed it cannot tell codes apart. Mixing two codes of one fund and quarter still scores
  at least 0.90 in 54 of 73 pairs whose medians differ by 2 points or more (three centres of radius 0.30 cover two
  tight clusters); reading the all-in rate as the spread gives implied base 0 on every row, which clusters perfectly;
  zero is an admissible centre.

Both stay as measurements; no model and no worklist state reads them. A level check needs a table of each base rate
(SOFR term tenors, SONIA, EURIBOR, CORRA, ...) at each report date. No such table is in the repository; none was
fetched (no network).

### 13.2 Passing is per row

A read position counts as checked only when the check tested that row: its own filing's legend agrees with the rule
that read it. Read statuses: `read_and_checked` (legend agrees), `read_unchecked` (no legend for the code in the
filing, or none with an abbreviation), `read_failed` (mixed or contradicts), `read_unspecified` (read by a
`label_is_unspecified` rule, which names no rate; it never counts as read). States: covered (95% read_and_checked),
covered_unchecked (95% read, fewer checked), partly_covered, failed_check, uncovered. Unit test
`int_text_worklist_states` rewritten (eight units: covered, partly, unchecked, mixed checked and unchecked, failed,
unspecified-only, no rule, nothing read).

State counts (`scripts/text/q_r8_worklist.sql`), covered / covered_unchecked / partly_covered / failed_check / uncovered:

| Fund | Columns, fix round 1 | Columns, fix round 2 | Shapes, fix round 1 | Shapes, fix round 2 |
|---|---|---|---|---|
| Ares | 0/0/1/0/13 | 0/0/1/0/13 | 3/12/0/0/27 | 0/12/0/0/30 |
| BCRED | 0/0/5/2/57 | 0/0/6/1/57 | 31/1/0/2/61 | 32/1/0/1/61 |
| Blue Owl | 0/0/3/1/39 | 0/0/3/1/39 | 7/8/0/1/33 | 7/8/0/1/33 |
| Apollo | 0/0/2/0/14 | 0/0/2/0/14 | 4/2/0/0/59 | 4/2/0/0/59 |
| HPS | 0/0/0/1/11 | 0/0/0/1/11 | 12/0/0/2/21 | 12/0/0/2/21 |

- Ares's 3 "Base Rate (Q)" shapes, covered in round 1 with no legend agreement, are now uncovered (read_unspecified
  only). Its Reference column: 144 read, 0 checked, 144 unchecked, 397 unspecified, of 13,657.
- BCRED [7bedc6] is partly covered now (its 2023-03-31 failure came from the cluster test); [fc9493] still fails, for
  2022-12-31 only (12 positions under the filing that defines S two ways).
- Blue Owl [256066]: 3,451 read, 5 checked, 3,444 unchecked, 2 failed (2024-12-31). HPS [836097]: 452 read, 434
  checked, 18 failed (2024-12-31, 2025-06-30 to 2025-12-31).
- Still no column is covered.

### 13.3 Bundles

- legs: every (printed number, tagged field) pair of a parts-stating shape, over interest_rate, interest_rate_cash,
  pik_rate and spread, zero matches kept. Apollo "S+# Cash plus #% PIK, #% Floor" (62 rows) now shows n2 = pik_rate on
  62 of 62, n1 against pik_rate 0 equal (3 as basis points), and spread, rate and cash rate "compared 0": none of those
  rows carries those tags.
- `legs_help`: one sentence each for n1/n2, compared, equal, equal_bps.
- Legend entries: only filings inside the column's own first-to-last report dates; `legend_entries_outside` counts the
  (entry, filing) pairs left out: BCRED 557, Blue Owl 107, Apollo 68, Ares 0, HPS 0.
- 31 bundles, 242,936 bytes; all 31 hashes changed against fix round 1 (every bundle gained `legs_help` and
  `legend_entries_outside`).

### 13.4 Small items

- `tests/seed_sofr_hash_matches.sql` also compares the loaded seed table with the file read now (md5 over date,value
  lines, both typed alike), so a file edited after the last load fails.
- `pytests/test_text_models_no_production.py` also fails when an `int_text_*` model, or a macro it calls, uses
  `source(` or a DuckDB file reader (`read_text`, `read_csv`, `read_parquet`, `read_json`, ...); a guard test plants a
  source(), a read_csv and a read inside a called macro and checks all three are found. The reader names are listed
  because a plain `read_` pattern matched the column name `read_failed`.

### 13.5 Build

Full build (`dbt.ps1 build --threads 2`): `PASS=996 WARN=123 ERROR=0 TOTAL=1119`. CI fixture (local, new folder): step 4
`PASS=3`; build `PASS=589 WARN=5 ERROR=0 TOTAL=594`; empty run `PASS=2`; unit-test and drift step `PASS=62`. pytests:
180 passed. Baseline ceilings unchanged (2,272 / 43,437 / 4 / 12).
