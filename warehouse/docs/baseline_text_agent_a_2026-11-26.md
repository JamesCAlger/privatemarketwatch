# Text slice A: test of Agent A's Apollo grammar and anchors (2026-11-26)

Plan: `2026-11-26-text-plan.md`, slice A. Decision 19-T10: test Agent A's files; fold in if useful, redo if not.
Measurement only: no model, no dbt model, no file outside `warehouse/scripts/text/` and this note.

Agreement with production or with a tag is not correctness. The printed row was used to settle disagreements; it was
matched by text, not read by a person.

## What was tested

- Files: `data/overrides/identifier_rate_grammars/0001837532.json` (version 3, 6 extractors) and
  `data/overrides/identifier_anchors/0001837532.json`. Read, not copied or changed.
- Applied in SQL to the label of every published Apollo position both pipelines hold: 7,290 rows, 14 quarters
  (2023-03-31 to 2026-06-30). Queries: `scripts/text/q_a1_grammar_vs_tags.sql`, `q_a3_disagreements.sql`,
  `q_a3_printed_line.sql`.
- One pattern could not run as written: the interest-rate extractor ends in a lookahead, which DuckDB's regex
  engine does not support. It was rewritten to consume the same text; the value read is the same.

## A1, A2: the grammar against the tags

| Field | Label read | Tag also present | Agree | Disagree | Tag only | Label only |
|---|---:|---:|---:|---:|---:|---:|
| Maturity date | 7,014 | 7,000 | 6,902 (98.6%) | 98 | 35 | 14 |
| Spread | 6,675 | 6,455 | 6,359 (98.5%) | 96 | 22 | 220 |
| Interest rate | 311 | 234 | 227 | 7 | not counted | 77 |
| PIK rate | 266 | 254 | 251 | 3 | 18 | 12 |
| Reference rate | 6,675 | no tag exists | | | | 6,675 |
| Floor | 6,653 | no tag exists | | | | 6,653 |

Per quarter the picture is the same (file `scratch/2026-11-25_text_spec/a1_grammar_vs_tags.tsv`); no quarter fails.

## A3: where label and tag disagree, the printed row decides

For the 194 disagreements on spread and maturity, the printed row holding the position's fair value was found in all
194 cases.

| Field | Page shows the tag's value | Page shows the label's value |
|---|---:|---:|
| Maturity | 98 | 0 |
| Spread | 94 | 2 |

- 192 of 194: the label is stale. The label is the name of an XBRL member; the filer reuses it across quarters
  and does not always update it when the loan's terms change. Example: label "E+650", printed cell "E+600", tag 6.0.
- 2 of 194: the tag is wrong (0.38 tagged for a printed S+385; the floor 0.50 tagged as the spread). Both are
  already row corrections, and the grammar reproduces both.
- Agent A's own design note says the same of other funds ("about 80% of maturity disagreements are the descriptor
  being stale").

Against the row corrections on these fields:

| Field | Corrections | Grammar reproduces | Grammar differs | Label has none | Correction withdraws a value |
|---|---:|---:|---:|---:|---:|
| Reference rate type | 50 | 36 | 1 | 0 | 13 |
| Spread | 16 | 2 | 1 | 0 | 13 |
| Interest rate | 25 | 5 | 1 | 5 | 14 |
| PIK rate | 13 | 0 | 0 | 2 | 11 |
| Coupon type | 13 | not read by the grammar | | | |

Reference rate against production (no tag exists): same on 6,596 rows, both empty 601, different 76, one side only
17. Of the 76: "C" left unmapped by the grammar where production has CORRA (23); "K", "T", "N" unmapped where
production has SOFR (19); the rest are LIBOR, PRIME, EURIBOR against SOFR in either direction (33) and one other.
Which side is right on those was not checked.

## A4: the existing gate

Not run: `pipeline/identifier_held_out.py` has no Apollo target, and running it needs a new Python script against
production's holdings file. Read instead. For Apollo's grammar the gate reduces to one test: a maturity date is
found on at least 90% of the rows of the signature in every quarter, and the share of labels with no signature does
not jump. Restated on the rows whose label carries rate text: the lowest quarter is 97.6% (2024-06-30), so it would
pass. This is an approximation of the signature, not the gate's own count.

The gate checks that something was read. It checks no value. Comparisons with the tag are advisory in it.

## A5: recommendation (owner decides)

**Do not fold the grammar in as a source of values. Keep three parts of Agent A.**

Why not as a source:

1. For spread and maturity the tag exists on 97% and 99.8% of rows where the label has a value, and where the two
   differ the page sides with the tag 192 times of 194. Reading the label adds stale values.
2. For reference rate and floor, which have no tag, the printed row carries the same text in its own cell
   ("S+475, 0.75% Floor"), current for the quarter. That cell is the better source, and it is what slice R reads.
3. The gate that accepted the grammar tests coverage, not values.

What to keep:

| Part | Use |
|---|---|
| The method (a rule per shape, code applies it, a check accepts it) | Already the method of the spec (19-T1) |
| The anchor file's list of Apollo industry names | Starting vocabulary for the industry heading or label prefix (slices I and L). To be checked against the page's headings |
| The reference-code map ("S" is SOFR, "E" is EURIBOR) | Starting vocabulary for the reference-rate codes in slice R. Gaps to settle from the filing's own legend: C, K, T, N |

A possible fourth use, not recommended now: the label reading as a check that flags a stale label. It flags the
label, which nothing publishes.

## What this changes in the plan

- Slice R reads Apollo's rate text from the printed cell, like the other four funds. The label's rate text is not a
  source.
- Slice L for Apollo shrinks: the label is needed for the issuer and instrument only if the page does not print
  them in their own cells. The samples show the issuer and the instrument printed in separate cells; slice P
  measures that on every filing.
- Owner question 1 of the plan (copy Agent A's files into `warehouse/`) falls away if this recommendation is taken:
  only the two vocabularies are carried, as proposed rule rows.

## Not done

- No person read a page. "Page shows the tag's value" is a text match on the printed row.
- The 220 spreads and 14 maturities the label has and the tag lacks were not checked against the page.
- The 76 reference-rate differences with production were not settled.
- The gate was read, not run.

## A5 revised after the owner's comment (2026-11-26)

Owner: "98.5% sounds quite good, with some corrections." Accepted in part. The grammar is a good parser: the 1.5%
is the label being out of date, not the grammar misreading it. The recommendation above was too strong.

Revised recommendation: fold the grammar in as a second source, never the first.

| Field | First source | Label grammar's role |
|---|---|---|
| Spread, maturity, rate, PIK | The tag (D6: the tag wins) | Fills the value where the tag is absent (220 spreads, 14 maturities, 77 rates, 12 PIK rates). A difference from the tag is recorded, not applied |
| Reference rate, floor (no tag) | The label grammar now; the printed cell once slice R reads it | After slice R: the check on the cell, and the value where the cell cannot be read |

Limit on "with some corrections": a stale spread or maturity is caught by the tag, so no correction is needed there.
A stale reference rate or floor cannot be caught from the label alone, because nothing tagged contradicts it; only
the printed cell shows it. Until slice R, those two fields carry an unmeasured share of stale values (for spread it
is 1.5%). They are published with the rule named, so they can be told apart later.

## A6: the stale share, measured (owner question, 2026-11-26)

`scripts/text/q_a6_label_vs_cell.sql`. The same patterns applied to the printed row of each of the 7,290 positions,
compared with the label's reading. This replaces "unmeasured" above.

| Field | Same | Differ | Label only | Cell only | Neither | No printed row found |
|---|---:|---:|---:|---:|---:|---:|
| Reference rate | 6,637 | 34 (0.5%) | 3 | 14 | 558 | 44 |
| Spread | 6,571 | 100 (1.5%) | 3 | 14 | 558 | 44 |
| Floor | 6,567 | 45 (0.7%) | 40 | 9 | 585 | 44 |

- The printed row is readable with the grammar's own patterns on all but 44 positions, so the cell can be the first
  source for reference rate and floor now, without waiting for slice R's agent run. The label is then the check.
- Not settled: the 44 positions with no printed row found, and the 40 floors the label has and the row lacks.
- Still a text match by code; no person read a page.
