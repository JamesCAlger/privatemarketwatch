# Row roles baseline, 2026-11-19 (slice 2 of the intermediate layer)

The set of position rows this layer produces, compared with production's. Plan:
`2026-11-19-slice2-row-roles-plan.md`. Spec: `intermediate_spine.md` sections 6.2 and 8 (D1).
Models: `cmp_row_set`, `cmp_excluded_quarter`. Production: `stg_holdings`, build of record b1116a.
State: after Task 2 fix rounds 2, 3 and 3b (commits 1e9b9121, a09bee83), Task 3 fix round 1, the
owner's decisions of 2026-11-19, and Task 5 (fund rules moved into the new pipeline's wrapper
copies; one Blue Owl relabel added; the Apollo subtotal rule). Task 5's report has the before and
after measurements.

Agreement with production shows the two agree. It does not show either is right. Where a cause
below leans on the filed total, the evidence is a measured tie of sums. A tie is a proxy: it says
nothing about rows with zero value, about which row carries which value, or about offsetting errors.

Build line: see the Task 3 report, Fix round 1.

## How the sides are joined

- Key: accession and context id. No position id.
- Published basis. New: role `position` and `is_published`. Production: `accounting_record_class`
  is not `underlying_schedule`.
- Unpublished basis (a JV's own schedule). New: role `position`, not published. Production:
  `underlying_schedule`.
- One row per basis, accession and context. A test fails if any accession and context appears in both
  bases, so accession and context is unique as well.
- Production rows with no context id: 0 (`baseline_cmp_row_set_no_context`, ceiling 0).

## Quarters left out of the comparison

Owner decision 2026-11-19: a fund-quarter that production has no rows for is left out. Listed in
`cmp_excluded_quarter`, ceiling 3 fund-quarters (`baseline_cmp_excluded_quarter`). The set itself is
pinned (Task 5): `tests/cmp_excluded_quarter_set.sql` fails on any quarter not in
`cmp_excluded_quarters_pinned` (`dbt_project.yml`), so a swap cannot pass the count.

| Fund | Date | Accession | Published rows | JV rows |
|---|---|---|---:|---:|
| Ares | 2026-09-30 | 0001628280-26-067383 | 1,422 | 0 |
| Blue Owl | 2026-09-30 | 0001812554-26-000060 | 807 | 0 |
| Apollo | 2026-09-30 | 0001193125-26-449955 | 786 | 0 |

Production has not been built with these filings (Task 1: absent from `bdc_filings_index.csv` and
from holdings). They re-enter the comparison when it is.

## Published basis, per fund

Rows and fair value ($bn), all compared quarters. "Prod FV" is production's value, "new FV" this
layer's.

| Fund | Both | Both, prod FV | Both, new FV | New only | New only, new FV | Prod only | Prod only, prod FV | Prod only, new FV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Ares | 19,723 | 402.92 | 402.92 | 2 | 0.12 | 56 | 0.42 | 0.30 |
| BCRED | 15,457 | 960.52 | 960.52 | 32 | 3.78 | 42 | 29.78 | 29.78 |
| Blue Owl | 9,717 | 350.39 | 350.39 | 1 | 0 | 2 | 0.001 | 0.001 |
| Apollo | 7,248 | 205.70 | 205.70 | 0 | 0 | 50 | 0.18 | 0.18 |
| HPS | 8,431 | 214.98 | 214.98 | 0 | 0 | 11 | 3.36 | 3.36 |
| Total | 60,576 | 2,134.51 | 2,134.51 | 35 | 3.91 | 161 | 33.75 | 33.63 |

- "Prod only, new FV" is this layer's fair value for the same context, where it has one. It is lower
  for Ares because 2 production rows sit on contexts with no fair value of their own (the Expereo pair).
- On rows on both sides, Apollo differs by 3,272,000 at 2026-03-31: two rows whose sign production
  corrects (`baseline_filed_fair_value_differs_corrected`). Value fields are slice 3.
- Blue Owl at 2026-03-31: 864 published here, 863 in production; the extra one is c-1013 below.

## Unpublished basis (JV schedules), per fund

| Fund | Both | Both FV ($bn) | New only | New only, new FV ($bn) | Prod only | Prod only, prod FV ($bn) |
|---|---:|---:|---:|---:|---:|---:|
| BCRED (Emerald, Verdelite) | 9,171 | 101.19 | 30 | 0.32 | 2 | 0.006 |
| Blue Owl (ORCIC Senior Loan Fund) | 1,416 | 8.31 | 0 | 0 | 0 | 0 |
| HPS (detached JV schedule) | 119 | 11.72 | 0 | 0 | 32 | -0.003 |

Both sides put all 1,416 Blue Owl `ORCICSeniorLoanFundMember` rows in a JV schedule.

## Causes per basis

`cause` is set in `cmp_row_set` by rules on row features, first match wins. Each count has its own
ceiling (`baseline_cmp_<basis>_<cause>`).

| Cause | Published | Unpublished | Detail |
|---|---:|---:|---|
| new_wrong | 54 | 0 | held_unresolved_ties_filed_total |
| owner_review | 45 | 34 | held_unresolved_d5 |
| needs_correction | 52 | 0 | correction_supplies_value_or_term |
| needs_store_not_loaded | 12 | 0 | production_row_added 8, rate_only_context_pair 4 |
| convention | 31 | 30 | cash_published_d7 |
| not_yet_explained | 2 | 0 | none 1, relabel_loaded 1 (a relabel is on file; not a cause) |
| old_wrong | 0 | 0 | no rule |

`old_wrong` has no rule: no group measured here shows production reading a filing wrongly. Its
ceilings are 0.

### What each rule tests and what was measured

**new_wrong, held_unresolved_ties_filed_total (54).** Production only; this layer holds the row
`unresolved`; fair value not 0; and in that fund and date this layer's published total without cash
misses the filed total investments, while adding the fund-quarter's group of such rows closes the
gap. Both within 500,000 (`reconcile_tolerance`). Measured per quarter:

| Fund | Rows | Quarters | Measured |
|---|---:|---|---|
| BCRED | 41 | 15 | Gap closed in all 15 quarters with rows, 2022-09-30 to 2026-06-30. From 2023-12-31 the group is the fund's own Emerald JV and Verdelite JV interests (2 rows a quarter, 1.64 to 2.16bn). Before that it also holds Specialty Lending Company LLC and co-invest units. 2023-09-30 has no gap and no rows. |
| HPS | 11 | 11 | ULTRA III LLC interest, 2023-12-31 to 2026-06-30. The gap equals its value in each quarter (e.g. 2026-03-31: 426,214,000). |
| Blue Owl | 1 | 1 | 2023-03-31, Insight CP (Blocker) Holdings LP interest, 987,000. |
| Ares | 1 | 1 | 2025-09-30, Merit Financial co-invest LP interests, 4,700,000. |

In every such quarter production's own total ties to the filed total (within 6,000). All 54 rows
were opened (see the owner-review section).

**owner_review, held_unresolved_d5 (45 published, 34 JV).** Production only; this layer holds the
row `unresolved` under D5; not tied by the rule above; no rule change proposed here. Classified row
by row in the owner-review section.

**needs_correction (52).** Corrections are not applied in this slice.
- correction_supplies_value_or_term (52): production only and a loaded context-keyed value
  correction names the context with fair value or a term field. Apollo 44: `wrapper:untagged_values`
  fair value 0, printed as a dash, no fact. Apollo 6 and Ares 2: untagged principal and cost. Opened
  4, 4 and 2 printed rows: the number is printed and not tagged.

**needs_store_not_loaded (12).**
- production_row_added (8): production's `corrected_fields` has `_row:added`. Ares 2025-03-31 and
  2025-06-30, contexts on `InvestmentIssuerNameAxis` with no identifier member. Store:
  `data/overrides/agent_investigate_rules/1287750/recover_2025q1_values_tagged_on_issuer_axis.json`
  (c-1033, c-1491, c-1679, c-1699) and `recover_2025q2_values_tagged_on_issuer_axis.json` (c-1171,
  c-1590, c-1729, c-1750). Read both; all 8 match. Opened 8 printed rows: loans and units.
- rate_only_context_pair (2 production only + 2 new only): same accession and label; the production
  context carries rate facts and no fair value; the filer has an unloaded `rate_only_contexts`
  declaration. Ares "Expereo USA, Inc. and Ristretto Bidco B.V." 2025-03-31 (c-1727 / c-1728) and
  2025-06-30 (c-1775 / c-1776). Both sides carry the position; production keys it to the rate
  context, this layer to the value context. Declaration: Ares wrapper `rate_only_contexts:
  adopt_adjacent` (`pipeline/source_encodings.py`). The function's docstring says the value context
  is kept; production's rows carry the rate context id. Not followed up.

Ares's gaps to the filed total equal these groups: 2022-09-30 166.8m (2 `needs_correction` rows
138.3m + 32 `owner_review` rows 28.5m; the tie rule does not count the correction rows, so those 32
stay `owner_review`), 2025-03-31 96.6m (row_added 94.3m + owner_review 2.3m), 2025-06-30 33.2m
(row_added), 2025-09-30 4.7m (new_wrong). 2024-06-30 is short by exactly 500,000 (one owner_review
row), inside the tolerance. In the other 11 quarters this layer ties.

**convention, cash_published_d7 (31 published, 30 JV).** New only and the row is cash (`is_cash`).
BCRED money-market and liquidity funds (State Street, Fidelity, Dreyfus, BlackRock, Morgan Stanley).
All 61 labels read. Decision D7, and owner decision 2026-11-19: keep cash; accepted as an intended
difference. Measured on production's side: it drops these BCRED rows (`pipeline/bdc_xbrl_wrapper.py`
treats money-market names as non-private-market rows) and publishes Apollo's money-market rows (8,
asset category CASH, on both sides here). Neither side is called right by this.

**not_yet_explained (2).**
- BCRED 2025-06-30 c-1259, "Box Co-Invest Blocker, LLC - (BP Alpha Holdings, LP) - Class C Preferred
  Units", fair value 0, cost 390,000. Production has the line in every other quarter from 2023-09-30.
  Production code not read for it.

- Blue Owl c-1013, below (detail `relabel_loaded` since Task 5).

**Blue Owl c-1013 (not_yet_explained, detail relabel_loaded).**
- Blue Owl 2026-03-31, 0001812554-26-000027 c-1013, "LSI Financing LLC, Common Equity", fair value 0
  (filer commitment concept), commitment 171,438,000. Checked:
  1. Corrections: no `stg_correction` row names c-1013 or LSI in that filing. The 201
     `relabelled_contexts` entries for the filing cover c-686 to c-941 only.
  2. The printed row of all three of c-1013's facts (row 1452) is "OWL-HP FINANCE LLC | Specialty
     finance equity investment | N/A | 44,062 | 171,438 | -". The filer's member names LSI Financing
     LLC; the line printed is OWL-HP FINANCE's commitment. It is the only comma-form label among the
     filing's 338 commitment lines.
  3. Production's raw extraction (`data/output/bdc_holdings.parquet`) has c-1013 with fair value 0;
     so production drops it after extraction, in staging or later.
  4. Read in `pipeline/staging_bdc.py`: the fair-value requirement, the two rollup filters, the
     reviewed aggregate-header flags (no LSI entry in `aggregate_header_flags.csv`) and the
     affiliation dedupe; none plainly removes it. Production's wrapper classifier marks "common
     equity" as an equity leaf, so the wrapper does not drop it.
  5. Not done: run production's staging on that filing (needs pandas; not in `warehouse/.venv`).
  Both layers carry the wrong company name if they publish it.
  6. Task 5 (owner: "implement the blue owl amendment"): one entry added to `relabelled_contexts` in
     the new pipeline's copy `warehouse/wrappers/0001812554.json`, in the form of the 201 already
     there: `0001812554-26-000027 c-1013 :: LSI Financing LLC, Common Equity :: OWL-HP FINANCE LLC |
     Specialty finance equity investment`. Checked first: the member as filed
     (`stg_filed_context_member`), the three facts (fees-concept fair value 0, commitment 171,438,000,
     contractually required 44,062,000), printed row 1452 as above, sibling c-1012 on row 1451 ("LSI
     Financing LLC | Specialty finance equity investment", the label form used), and that no stored
     correction named c-1013. Production's wrapper is unchanged, so production still has 201.
     Not applied in this slice. The relabel fixes the name the row carries; why production omits the
     row is not known. So the row stays `not_yet_explained`, with detail `relabel_loaded` to show the
     relabel is on file (Task 5 fix round 1; an earlier version made the relabel a cause).

## Blue Owl commitment lines

Through the filer-concept rule, this layer publishes Blue Owl's unfunded-commitment lines. Owner
decision 2026-11-19: they are positions for now, to match production.

| | Rows | Fair value |
|---|---:|---:|
| Published on both sides, not zero | 684 | -112.6m |
| Published on both sides, zero | 1,271 | 0 |
| New only, 2026-03-31 (c-1013) | 1 | 0 |

(The 314 lines in the 2026-09-30 filing are in the excluded quarter.)

- Only the non-zero lines are tested by the tie to the filed total: with them, this layer's Blue Owl
  total ties in each quarter 2025-03-31 to 2026-06-30 and is 89,000 over at 2024-12-31, where
  production is over by the same amount.
- The zero-value lines rest only on "production publishes them". The tie cannot see them.
- Whether an unfunded commitment should be a position at all stays open, for after reproduction.

## Apollo cash and the filed total

- Production's Apollo total including cash rows is above the filed total investments by exactly the
  filed cash equivalents from 2023-09-30 (except 2024-03-31, which has none), within 6,000.
  Production's total without cash rows ties.
- This layer's Apollo total without cash ties at 2023-03-31, 2023-06-30, 2023-12-31, 2024-03-31,
  2024-12-31 and from 2025-06-30 to 2026-06-30 except 2026-03-31. The misses (2023-09-30 -33.3m,
  2024-06-30 -41.6m, 2024-09-30 -12.3m, 2025-03-31 -67.2m, 2026-03-31 -29.5m) are the
  `needs_correction` rows and, at 2026-03-31, the sign-flipped pair.
- Apollo's cash rows are published here on D7 and the owner's 2026-11-19 decision, not on a tie.

## Fund rules now in force

**One place: `warehouse/wrappers/<cik>.json`.** Owner decision 2026-11-19 ("copy the wrappers"):
the new pipeline reads its own copy of each v0.5 fund's wrapper, taken byte for byte from
`data/overrides/bdc_xbrl_wrappers/` (commit 951b2226; `warehouse/wrappers/_source.json` records each
production file's SHA-256 and git blob id). Production keeps and reads its own wrappers until
cutover; neither they nor the production wrapper schema were changed. From now on the new
pipeline's fund rules are edited in `warehouse/wrappers/`. A change made to a production wrapper is
not seen by the new pipeline and must be carried into the copy by hand until cutover: the loader
compares each production wrapper with its recorded hash (table `wrapper_drift`, manifest key
`production_wrappers_changed`), and `baseline_production_wrapper_changed` (ceiling 0) fails the
build when one has changed.

The old-style declarations (`source_encodings`, `identifier_format`) load as before. New-style rules
sit in the copy's top-level `reading_rules` list (origin `wrapper:reading_rules`, class
`fund_rule`). The seed `seeds/filer_concept.csv` (48 rows, one per dated namespace) is deleted.

| Fund | Action | Concept and namespace glob | Read as | Status |
|---|---|---|---|---|
| Ares | concept_is_term_fact | InvestmentOwnedBalancePercentOfShares, `http://www.arescapitalcorp.com/*` | term fact | Controller ruling 2026-11-19 |
| Apollo | concept_is_fair_value | InvestmentOwnedAtFairValueAfterCashEquivalents, `http://gwms.apollo.com/*` | fair value where no us-gaap fair value | Controller ruling 2026-11-19 |
| Blue Owl | concept_is_fair_value | InvestmentOwnedFairValueNetOfUnamortizedFees, `http://owlrockcoreincomecorp.com/*` | fair value where no us-gaap fair value | Owner confirmed (D11) |
| Blue Owl | concept_is_term_fact | the same concept and glob | term fact | Owner confirmed (D11) |
| Apollo | subtotal_on_fair_value | none | rule 6 on fair value alone | Owner decision D12 |

- One rule per fund and reading, with a namespace glob for the filer's own domain (no wildcard in
  the host; ruling 12: never the local name alone). It matches exactly the facts the 48 seed rows
  matched: 4,963 fair-value and 5,376 term facts, none on one side only
  (`scripts/slice2/q_t5_rule_vs_seed_facts.sql`). A new dated namespace is read without an edit;
  `tests/concept_rule_namespace_gaps.sql` fails if a fund with a concept rule files the same local
  name in a namespace the rule does not match, or if a rule matches nothing.
- Blue Owl's two rules on one concept switch off the term-fact cross-check for its commitment lines.
  `baseline_concept_rule_value_and_term` (ceiling 0) fails on a published line whose value and term
  fact both come from concept rules and that has a positive fair value or a total-like label (rule
  4 patterns). Measured: 0.
- The move changed no role, rule, reason, scope or flag on any of 288,935 contexts, and no
  comparison count; every rule id changed (loader version 2 adds two selector columns) and maps one
  to one (`scripts/slice2/q_t5_compare.sql`, `q_t5_compare_cmp.sql`).
- The Apollo subtotal rule changed 140 contexts, all `unresolved` to `aggregate` by rule 6: 120
  whose cost differs (`scripts/slice2/q_apollo_cost_differs_rollups.sql`, 6.59bn) and 20 whose
  cost cannot be compared (1.61bn). None has a row in production's holdings, none carries a rate,
  spread, PIK rate, maturity, principal or shares, and Apollo's published total per quarter is the
  same before and after (`scripts/slice2/q_t5_apollo_rule_effect.sql`, `q_t5_apollo_rule_summary.sql`).
- For the owner: rollups the rule removes whose own cost differs from the summed cost of the rows
  directly beneath by more than 10 percent of that sum (`scripts/slice2/q_apollo_rule_cost_gap.sql`;
  $m; fair value ties in every case). A large cost gap with an exact fair-value tie may mean a
  position beneath the rollup that carries cost and no fair value and is not tagged. Fair-value
  totals are unaffected either way. Listed for review; the rule is not changed. The 20 rollups whose
  cost cannot be compared have no gap to measure and are not in this list.

| Date | Rollup label | Rollup cost | Cost beneath | Rollup FV | FV beneath | Rows beneath |
|---|---|---:|---:|---:|---:|---:|
| 2024-12-31 | Chemicals Heubach | 11.002 | 1.457 | 0.828 | 0.828 | 1 |
| 2024-12-31 | Media Material+ | 7.951 | 6.375 | 5.642 | 5.642 | 1 |
| 2025-03-31 | Chemicals Heubach | 9.816 | 0.385 | 0.243 | 0.243 | 1 |
| 2025-03-31 | Media Material+ Material Holdings, LLC | 8.109 | 6.533 | 4.051 | 4.051 | 1 |

## For the owner's review (decision D5)

### The rows production publishes and this layer holds (133)

Every row was opened: its printed line and every fact on its context (`stg_filed_document_row`,
`stg_filed_fact_placement`, `stg_filed_fact`). Full list:
`warehouse/docs/owner_review_rows_2026-11-19.csv` (cik, report_date, accession, context_id, label,
fair_value, class; plus basis and cause). These are the `new_wrong` (54) and `owner_review` (79)
rows. No role was changed.

| Class | Fund | Rows | Cause | Production |
|---|---|---:|---|---|
| own_jv_or_fund_interest | BCRED | 33 | new_wrong | publishes |
| own_jv_or_fund_interest | HPS | 11 | new_wrong | publishes |
| equity_or_fund_interest_no_units_tagged | Ares | 10 | 1 new_wrong, 9 owner_review | publishes |
| equity_or_fund_interest_no_units_tagged | BCRED | 11 | 8 new_wrong, 1 owner_review (Pigments LP, FV 0), 2 owner_review (JV) | publishes (9), JV schedule (2) |
| equity_or_fund_interest_no_units_tagged | Blue Owl | 1 | new_wrong | publishes |
| undrawn_revolver_zero_value | Ares | 34 | owner_review | publishes |
| unfunded_commitment_line | Blue Owl | 1 | owner_review | publishes |
| unfunded_commitment_line | HPS | 32 | owner_review (JV) | JV schedule |
| position_with_terms_on_another_context | | 0 | | none seen |
| other | | 0 | | none seen |

**own_jv_or_fund_interest (44).** The fund's own interest in a joint venture or a fund it holds. The
printed line has cost, fair value and percent of net assets, and no instrument column, rate or units.
- Examples: BCRED 2026-03-31 c-1420 "BCRED Emerald JV LP - LP Interest | (6)(16) | 1/19/2022 |
  1,836,000 | 1,539,677 | 3.41"; HPS 2026-03-31 c-952 "ULTRA III, LLC (5)(20)(22) - LLC Interest |
  $ 421,029 | $ 426,214".
- Fair value by quarter ($m): BCRED (Emerald, Verdelite, and Specialty Lending Company LLC to
  2023-06-30) 2,046.2, 2,360.7, 2,293.9, 2,302.9 (2022-09-30 to 2023-06-30), then 2,161.5, 2,160.7,
  1,956.8, 1,923.7, 1,914.4, 1,849.8, 1,863.9, 1,835.9, 1,791.8, 1,636.8, 1,660.3 (2023-12-31 to
  2026-06-30). HPS 124.0, 163.3, 238.6, 284.5, 320.4, 322.6, 323.8, 328.1, 416.2, 426.2, 415.4
  (2023-12-31 to 2026-06-30).
- Short of the filed total without them: yes, in every quarter with rows. HPS: by exactly this
  value. BCRED: from 2023-12-31 by exactly this value; before that by this value plus the BCRED
  co-invest units below.
- Smallest rule: a fund rule in the wrapper naming the fund's own JV and fund interests as positions
  (BCRED: Emerald JV, Verdelite JV, Specialty Lending Company; HPS: ULTRA III). No general structural
  rule found: the same shape (cost and fair value, no term) is also the shape of the rollups production
  leaves out.

**equity_or_fund_interest_no_units_tagged (22).** An equity, LP, co-invest or warrant line whose
units or shares are printed (or not printed at all) but not tagged. 7 have fair value 0.
- Examples: Ares 2022-09-30 "GHX Ultimate Parent Corporation, Commerce Parent, Inc. and Commerce
  Topco, LLC, Class A units": printed "Class A units | 6/2017 | 14,853,569 | 15.7 | 28.5", only cost
  and fair value tagged. BCRED 2023-06-30 c-876 "GSO DL Co-Invest EIS LP (EIS Acquisition Holdings,
  LP) - Class A Common Units | 558 | 2,779 | 0.01": no units printed.
- Fair value by quarter ($m): Ares 28.5 (2022-09-30), 0 (2022-12-31, 2023-03-31), 0.5 (2024-06-30),
  2.3 (2025-03-31), 4.7 (2025-09-30); BCRED 4.2, 4.7, 5.1, 4.8 (2022-09-30 to 2023-06-30) plus 6.4 in
  the Emerald JV schedule (2022-09-30); Blue Owl 1.0 (2023-03-31).
- Short of the filed total without them: BCRED, yes (part of the gap above); Blue Owl 2023-03-31 and
  Ares 2025-09-30, by exactly this value; Ares 2022-09-30, 2025-03-31 and 2024-06-30, the gap is
  this value plus rows with other causes (see Ares above); zero-value rows, not testable.
- Smallest rule: units read from print by a fund rule (D6: a field the filer never tags is read from
  print by a filer rule), or a correction per row. Not a general rule: Ares's Ultimus line even prints
  "8.00% PIK" untagged.

**undrawn_revolver_zero_value (34).** Ares first-lien revolving loan lines with fair value 0 and cost
0, no principal printed, only a dash. 29 in 2022-09-30, 3 in 2023-03-31, 2 in 2023-06-30.
- Examples: 2022-09-30 "Harvey Tool Company, LLC (15) | Manufacturer of cutting tools ... | First
  lien senior secured revolving loan | 10/2021 | 10/2027 | - | -"; 2023-06-30 c-1206 "Mavis Tire
  Express Services Topco Corp., Metis Holdco, Inc. and Metis Topco, LP (15) | ... | First lien senior
  secured revolving loan | 05/2021 | 05/2026 | - | -".
- Fair value: 0 in every quarter. The tie cannot test them.
- Smallest rule: a fund rule for Ares (a zero-value line whose label names a revolving loan is a
  position). A general rule was not measured: Ares has 125 other zero-value unresolved rows that
  production leaves out, not examined here.

**unfunded_commitment_line (33).** A commitment line with its commitment amount tagged and a fair
value (often negative, the cost of the undrawn line). HPS tags the amount with
`QualifiedAffordableHousingProjectInvestmentsCommitment` in its JV schedule; Blue Owl's one uses the
us-gaap commitment concept with a us-gaap fair value of 0.
- Examples: HPS 2026-03-31 c-3683 "Rsource Holdings, LLC | 1st Lien Senior Secured Delayed Draw Loan
  | 50,000 | (1,462)"; Blue Owl 2024-12-31 c-1230 "ACR Group Borrower, LLC | First lien senior secured
  delayed draw term loan | 5/2025 | $ 733 | $ 100 | $ -".
- Fair value by quarter ($m), HPS JV: -1.3, -0.4, 0.9, 1.0, 0.8, 0.7, 0.5, -2.2, -3.1 (2024-06-30 to
  2026-06-30); Blue Owl 0 (2024-12-31).
- Short of the filed total without them: not testable. HPS's are JV-schedule rows (no filed total for
  the JV here); Blue Owl's is 0.
- Smallest rule: fund rules in the wrappers, as for Blue Owl's commitment lines: the commitment
  amount counts as the line's term fact (HPS: its concept; Blue Owl: the us-gaap commitment concept,
  for this filer only, since 143 Ares aggregates carry it).

### All unresolved rows (603; 743 before the Apollo rule) by fund and why

Not published. FV in $m, all quarters.

| Fund | Why | Production publishes | Production leaves out | Production lacks the filing | JV schedule in production |
|---|---|---|---|---|---|
| Ares | no term fact, FV 0 | 40 | 125 | 9 | |
| Ares | no term fact, FV not 0 | 6 (174.3) | 23 (470.1) | 31 (5,306.7) | |
| BCRED | no term fact, FV 0 | 1 | | | |
| BCRED | no term fact, FV not 0 | 41 (29,778.2) | 1 (35.6) | | |
| BCRED | JV schedule, no term fact | | 1 (2.2) | | 2 (6.4) |
| Blue Owl | no term fact, FV 0 | 1 | | | |
| Blue Owl | no term fact, FV not 0 | 1 (1.0) | 54 (9,252.0) | 18 (3,337.7) | |
| Blue Owl | "Total ... Commitments" line: total pattern (rule 4) and a term fact disagree | | 32 (-203.4) | 7 (-33.0) | |
| Blue Owl | two filer fair values disagree on one context (rule 3) | | 5 | | |
| Apollo | no term fact, FV not 0 | 6 (180.7) | 156 (190,028.1); 296 (198,220.0) before the Apollo rule | | |
| HPS | no term fact, FV not 0 | 11 (3,363.1) | | | |
| HPS | JV schedule, no term fact | | | | 32 (-3.1) |

- The 39 Blue Owl "Total Portfolio Company Commitments" and "Total ... debt/equity commitments" lines
  carry the filer's fees concept (InvestmentOwnedFairValueNetOfUnamortizedFees, its fair value net of
  unamortized fees), which the Blue Owl term-fact rule counts as a term fact, so the cross-check
  disagrees with rule 4. (Corrected in Task 5: earlier text said "the commitment concept".) They are
  totals; production leaves them out.
- Apollo issuer rollups whose fair value ties to their children: 120 whose cost does not (6.59bn)
  and 20 whose cost is not comparable (1.61bn), all left out by production. Since Task 5 all 140 are
  aggregates through Apollo's fund rule subtotal_on_fair_value (D12). Still unresolved: 68 Apollo
  rollups whose fair value differs.
- The 6 Ares and 6 Apollo rows production publishes include 2 and 6 with a loaded correction
  (`needs_correction`).
- "Production lacks the filing" rows are in the excluded 2026-09-30 quarter.

## Filing selection (Task 1)

74 of 79 fund-quarters select the same accession as production. The rest: the three 2026-09-30
filings production has not loaded, and two cover-only filings refused (BCRED 2022-06-30, HPS
2022-12-31) where production has no rows either. Differs: 0.

## Not checked

- Value fields on matched rows (slice 3), beyond the fund totals above.
- Why production drops Box Co-Invest c-1259 and LSI Financing c-1013.
- Whether unfunded-commitment lines (Blue Owl, HPS JV) should be positions at all (after
  reproduction).
- Zero-value rows of any group against anything but production.
- Ares's 125 zero-value unresolved rows that production leaves out.
- The 1,413 label-keyed corrections (no context id) are not used by the cause rules.
- `bdc_aggregate_row_overrides.json` (Ares entries are exclusions; none touches a one-sided row) and
  `bdc_xbrl_html_section_bridges/` (one HPS proposed file) were read, not matched entry by entry.
- Funds outside the five.
