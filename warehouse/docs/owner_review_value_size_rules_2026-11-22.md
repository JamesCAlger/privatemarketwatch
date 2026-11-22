# Owner review: rules that decide from the size of a number (2026-11-22)

Slice 3 Task 3. The wrappers' `par_tagged_as_units` declarations are loaded as they are and applied in
`int_field_rule` / `int_field_normalised`. Each one decides whether a share count is really a loan's par by
comparing the count with the row's cost. That is a value-size test: a wrong number of the right size passes. No
threshold was changed. This list is for the owner to decide whether each rule should stay.

Passing tests show the rules ran as written. They do not show the rows they change are right.

## What the rules do

On a position with no principal and a share count above zero, the count (times 1, 1,000 or 1,000,000) becomes
the principal and shares is left empty. Ported from `pipeline/staging_bdc.py` (`par_scale`) and
`pipeline/source_encodings.py`.

| Mode | Threshold | Rows it may touch |
|---|---|---|
| `rows_near_cost` | count x k within 0.8 to 1.25 times cost; k is the first of 1, 1,000, 1,000,000 that fits | debt rows |
| `rated_rows_near_cost` | the same band | debt rows that carry a rate or a spread |
| `rows_within_twice_cost` | count x k within 0.5 to 2 times cost | debt rows |
| `whole_filing` (one accession) | no band, k = 1 | every debt row of the listed filing |
| `listed_rows_without_instrument` | no band, k = 1 | rows of the listed filing with no debt term fact and no equity word in the label |

One difference from production, forced by this slice: production tests "is a loan" from text
(`asset_category_final = 'LOAN'`). Text is not read until the second spec, so a debt term fact (rate, spread, PIK
rate or maturity) stands in for it. A label naming units, shares, stock, membership or warrants keeps its count, as
in production. How much this stand-in matters (all quarters):

| Fund | Mode | Rows in the band | Taken | Left: label names equity | Left: no debt term fact |
|---|---|---:|---:|---:|---:|
| Ares | rated_rows_near_cost | 2,174 | 2 | 1,717 | 455 |
| BCRED | rows_within_twice_cost | 878 | 80 | 526 | 272 |
| Blue Owl | rows_near_cost | 359 | 24 | 166 | 169 |
| Apollo | rows_near_cost | 146 | 1 | 88 | 57 |
| HPS | rows_near_cost | 564 | 478 (16 by this mode; the rest are in the 2026-03-31 filing, taken by whole_filing) | 59 | 27 |

Most rows in the band are equity whose units cost about a dollar each, which is why the band alone is unsafe.

Query: `warehouse/scripts/slice3/q_t3_value_size.sql`, `q_t3_value_size_examples.sql`, `q_t3_value_size_proxy.sql`.

## Each rule

### Ares Capital (0001287750): `rated_rows_near_cost`

Rows changed: 2, both 2023-06-30 (one at k = 1, one at k = 1,000,000).

| Accession | Context | Label | Count | Cost | k | Principal |
|---|---|---|---:|---:|---:|---:|
| 0001287750-23-000036 | c-80 | Cloud Software Group, Inc., Picard Parent, Inc., ... | 120,963,000 | 112,000,000 | 1 | 120,963,000 |
| 0001287750-23-000036 | c-784 | Senior Direct Lending Program, LLC, Subordinated certificates | 1,289 | 1,288,800,000 | 1,000,000 | 1,289,000,000 |

Only two rows exist.

### BCRED (0001803498): `rows_within_twice_cost`

Rows changed per quarter (all positions / published): 2022-12-31 3/2, 2023-03-31 3/2, 2023-06-30 3/2,
2023-09-30 3/2, 2023-12-31 2/1, 2024-03-31 2/1, 2024-06-30 2/1, 2024-09-30 11/10, 2024-12-31 16/15, 2025-03-31
21/20, 2025-06-30 2/1, 2025-09-30 3/2, 2025-12-31 3/2, 2026-03-31 3/2, 2026-06-30 3/2. Total 80 (65 published).

| Accession | Context | Label | Count | Cost | k | Principal |
|---|---|---|---:|---:|---:|---:|
| 0001803498-25-000038 | c-1108 | New Mountain CLO 7, Ltd. - Subordinated Notes | 19,368,300 | 16,899,000 | 1 | 19,368,300 |
| 0001803498-25-000038 | c-1101 | Galaxy 34 Clo Ltd - Subordinated Notes | 20,000,000 | 18,000,000 | 1 | 20,000,000 |
| 0001803498-25-000021 | c-1223 | Elmwood CLO II Ltd - Subordinated Notes | 8,650,000 | 5,981,000 | 1 | 8,650,000 |

The wide band exists for CLO subordinated notes bought at a discount; Elmwood above is at 0.69 of par.

### Blue Owl Credit Income (0001812554): `rows_near_cost`

Rows changed per quarter: 2023-03-31 9 (one at k = 1,000), 2024-03-31 1, 2025-03-31 2, 2025-06-30 3 (one at
1,000), 2025-09-30 3 (one at 1,000), 2025-12-31 3 (one at 1,000), 2026-03-31 2 (both at 1,000), 2026-06-30 1 (at
1,000). Total 24, all published.

| Accession | Context | Label | Count | Cost | k | Principal |
|---|---|---|---:|---:|---:|---:|
| 0001812554-26-000027 | c-567 | PCF Holdco, LLC (dba Trucordia) Preferred equity, Non-Affiliated Issuer | 19,423 | 22,779,000 | 1,000 | 19,423,000 |
| 0001812554-23-000014 | i9b65ce73... | Metis HoldCo, Inc. (dba Mavis Tire Express Services) | 12,296,000 | 12,001,000 | 1 | 12,296,000 |
| 0001812554-25-000081 | c-602 | Pluralsight, LLC, First lien senior secured loan 2 | 1,206,000 | 1,206,000 | 1 | 1,206,000 |

Watch PCF Holdco: a preferred equity line that carries a debt term fact, so the stand-in calls it debt. Production's
text test would probably class it as preferred equity and leave it; the comparison (Task 4) will show it.

### Apollo Debt Solutions (0001837532): `rows_near_cost`

Rows changed: 1, 2025-12-31, at k = 1,000.

| Accession | Context | Label | Count | Cost | k | Principal |
|---|---|---|---:|---:|---:|---:|
| 0001193125-26-102386 | C_ce6d8610... | Insurance Galway Galway Borrower LLC ... First Lien Secured Debt - Revolver | 524 | 504,000 | 1,000 | 524,000 |

Only one row exists.

### HPS Corporate Lending (0001838126): `rows_near_cost`, `whole_filing`, `listed_rows_without_instrument`

`rows_near_cost`, rows changed: 2024-03-31 2, 2024-06-30 4, 2024-09-30 4, 2024-12-31 4, 2025-03-31 1, 2026-06-30 1.
Total 16, all published (in the 2026-03-31 filing `whole_filing` wins, see below).

| Accession | Context | Label | Count | Cost | k | Principal |
|---|---|---|---:|---:|---:|---:|
| 0001838126-24-000079 | c-638 | Rapid Express Preferred, LLC 1 | 2,784,000 | 2,784,000 | 1 | 2,784,000 |
| 0001838126-25-000017 | c-730 | Rapid Express Preferred, LLC 2 | 5,868,000 | 5,868,000 | 1 | 5,868,000 |
| 0001838126-24-000079 | c-640 | Rapid Express Preferred, LLC 2 | 5,553,000 | 5,553,000 | 1 | 5,553,000 |

`whole_filing` (0001628280-26-033248, 10-Q for 2026-03-31; no band): 539 rows, all published.

| Context | Label | Count | Cost | Principal |
|---|---|---:|---:|---:|
| c-546 | Radwell Parent, LLC 1 | 150,328,000 | 148,172,000 | 150,328,000 |
| c-527 | Bamboo US BidCo LLC 1 | 2,840,000 | 2,817,000 | 2,840,000 |
| c-250 | Hobbs & Associates LLC | 15,319,000 | 15,269,000 | 15,319,000 |

`listed_rows_without_instrument` (same filing; no band): 126 rows, all published.

| Context | Label | Count | Cost | Principal |
|---|---|---:|---:|---:|
| c-749 | Stack Sports Buyer, LLC 3 | 21,553,000 | -269,000 | 21,553,000 |
| c-66 | Valence Surface Technologies LLC 4 | 13,777,000 | -269,000 | 13,777,000 |
| c-530 | Bamboo US BidCo LLC 4 | 21,254,000 | -372,000 | 21,254,000 |

These are undrawn commitments (negative cost); the count is the commitment amount, not drawn par. In the listed
filing a row that both `whole_filing` and `rows_near_cost` match takes `whole_filing`: at equal priority a rule that
names the filing is the more specific (int_field_rule). Production's wrapper comment says 696 of 835 positions in
that filing tag par as shares; here 665 rows (539 + 126) are converted. The 31 gap is not examined here; Task 4's
comparison will show it.

## Not a value-size rule, but listed for completeness

`units_tagged_as_par` (Blue Owl, filing 0001812554-23-000030) is filing-scoped and needs no band: 28 equity rows
take their unit count from the principal tag. Its equity test is also a stand-in (no debt term fact), in place of
production's text class EQUITY_COMMON or EQUITY_PREFERRED.

## Decisions for the owner

1. Keep, narrow or retire each row mode. The evidence for each is a handful of named rows in the production
   wrapper comments; none carries dates.
2. Whether the debt-term stand-in for "is a loan" is acceptable until the text spec, given rows like PCF Holdco.
