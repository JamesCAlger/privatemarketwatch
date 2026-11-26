# Text slice R: the agent's proposed rules for the rate columns (2026-11-26)

Plan `2026-11-26-text-plan.md`, slice R, steps 4 and 5. Phase 1 (units, checks, bundles) is in
`baseline_text_rates_phase1_2026-11-26.md`. This note covers the agent runs. Nothing here is accepted or applied:
no rule was written to a wrapper and no value was read into a field.

A passed check means a proposal is consistent with the filer's own tags and footnote legend. It does not mean a value
is correct. No page was read by a person. Production's values were not used.

## Set-up

- Units: the 31 rate-candidate columns of the five funds (129,883 position cells, 284 text shapes, 134 codes).
- One API request per column bundle, `claude-sonnet-5-5`, effort medium, sent twice with the answer options in
  forward and reversed order (owner decisions 2026-11-26: Sonnet, twice, API calls). Script
  `scripts/text/propose_rules.py`; scoring `scripts/text/evaluate_proposals.py`, `summarise_proposals.py`.
- The model returns data only: what the column holds (closed list), the role of each number in each shape (closed
  list), and the reference rate each code stands for, with its basis (legend, common usage, cannot tell).
- Three runs, as the bundles gained evidence: run 1 (0.97 USD), run 2 with a "PIK spread" role (1.01), run 3 with
  printed-number-against-tag evidence on every shape (1.23). Run 3 is the run of record:
  `warehouse/text_runs/2026-11-26_rates_run3/` (proposals, usage, scoring output, bundle hashes).

## Run 3 against the checks

| Proposed | Total | Same in both orders | Confirmed | Contradicted | No check possible |
|---|---:|---:|---:|---:|---:|
| What the column holds | 31 | 30 | 27 by the tags placed in the column | 0 | 3 (reference-rate code columns: no tag exists) |
| Role of each number, by shape | 284 shapes | 277 | 155 number roles equal the tagged value on 90%+ of rows | 0 | see below |
| Reference rate of each code | 134 | 131 | 107 by the filer's legend | 0 | 24 (no legend entry) |

Rows by how far their shape's reading is supported:

| Status | Shapes | Rows | Share |
|---|---:|---:|---:|
| Confirmed: every number a tag can test equals the tag | 141 | 104,732 | 80.6% |
| Untested: stable in both orders, but no tag exists to test it | 80 | 6,687 | 5.1% |
| No number in the shape (a code or word only: "SOFR (Q)", "N/A") | 57 | 18,385 | 14.2% |
| Unstable: the two orders differ | 6 | 79 | 0.1% |
| Contradicted by a tag | 0 | 0 | 0 |

Of the untested rows, 5,730 are share-of-net-assets columns (not a rate; admitted by the 20% rule of phase 1).
Floors are never testable: no filer tags a floor.

## What is left for the owner

1. One column where the orders differ: Blue Owl "Interest" (unit 0dd66cba), "rate terms" against "spread". It is a
   group header over the code and the spread, so both are defensible; "rate terms" matches the cells.
2. Three reference-rate code columns with no tag check: Blue Owl "Ref. Rate" (two table types), Ares "Reference".
3. Six unstable shapes, 79 rows:
   - "#%" in a "Reference Rate and Spread" column (BCRED, Blue Owl; 66 rows): a fixed rate, or a spread with the
     reference rate left out. The cell alone does not say.
   - "#% (#% PIK)" (Blue Owl, 7 rows): cash rate or spread.
   - Apollo "#% Cash plus #% PIK, #% Floor" (2 rows): all-in or cash. Production reads this wording two ways.
   - Apollo "S+# PIK" (4 rows): PIK spread in percent or spread in basis points.
4. Codes with no legend entry (24). Most name themselves ("SOFR", "LIBOR", "SONIA", "CORRA", "Euribor" in Ares'
   column). To look at: Apollo "N" (NIBOR in one answer, no answer in another; the legend defines "NOK"); "BB" as
   BBSY; "SORF" as SOFR (a filer typo); "Base Rate" and "CAD Base Rate" (name no rate); Blue Owl "SR", "L", "P".
5. Two codes the filer defines two ways: Apollo "T" (TONAR and, in one filing, MUTKCALM); Blue Owl "C" (CDOR, then
   CORRA). These need dated rules.
6. Three texts the code took for rate codes and the model rejected: "Equity plus", "Variable".

## Stability across the three runs

Column answers: 31 of 31, 30 of 30 scored, 30 of 31 same in both orders. Shapes: 274, 280, 277 of about 284. Codes:
133, 130, 131 of 134. The items that move are the same few genuine ambiguities each time. Not measured: the same
bundle sent many times with one option order.

## Limits

- The reference rate itself has no arithmetic check (phase 1 note, section 13): a code is confirmed only by the
  filer's legend. A level check needs base-rate tables by date; that needs a download and the owner's go.
- 2 of 62 replies in run 2 held two JSON objects and were not parsed; fixed in the script before run 3.
- The checks were computed by the scoring script from the evidence in each bundle, not yet as dbt models that judge
  a stored rule. That, the rule format in the wrapper, and applying the rules are the next step.
