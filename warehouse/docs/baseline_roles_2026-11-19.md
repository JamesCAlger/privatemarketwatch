# Row roles baseline, 2026-11-19 (slice 2 of the intermediate layer)

The set of position rows this layer produces, compared with production's. Plan:
`2026-11-19-slice2-row-roles-plan.md`. Spec: `intermediate_spine.md` sections 6.2 and 8 (D1).
Model: `cmp_row_set`. Production: `stg_holdings`, build of record b1116a.

Agreement with production shows the two agree. It does not show either is right. Where a cause below
says production is right, the evidence is named; most of it is the tie of fund totals to the filed
total, which is itself a proxy.

Build: `.\warehouse\dbt.ps1 build` -> `PASS=270 WARN=16 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=286`.

## How the sides are joined

- Key: accession and context id. No position id.
- Published basis. New: role `position` and `is_published`. Production: `accounting_record_class`
  is not `underlying_schedule`.
- Unpublished basis (a JV's own schedule). New: role `position`, not published. Production:
  `underlying_schedule`.
- Production rows with no context id: 0 (`baseline_cmp_row_set_no_context`, ceiling 0).
- Every production row's context exists in the filed layer and has a role.

## Published basis, per fund

FV in $bn, summed over all quarters.

| Fund | Both | New only | Production only | New only FV | Production only FV |
|---|---:|---:|---:|---:|---:|
| Ares 0001287750 | 19,465 | 1,410 | 314 | 27.20 | 25.70 |
| BCRED 0001803498 | 15,457 | 32 | 42 | 3.78 | 29.78 |
| Blue Owl 0001812554 | 7,762 | 493 | 1,957 | 35.13 | -0.11 |
| Apollo 0001837532 | 7,239 | 784 | 59 | 25.54 | 2.23 |
| HPS 0001838126 | 8,431 | 0 | 11 | 0 | 3.36 |
| Total | 58,354 | 2,719 | 2,383 | 91.66 | 61.27 |

Fair value on the rows on both sides is equal in total except Apollo (new 3.27m lower at
2026-03-31: the two sign-flipped rows production corrects, `baseline_filed_fair_value_differs_corrected`).
Value fields are slice 3; not checked further here.

Without the three Q3-2026 filings production has not loaded (2,685 rows), new only is 34.

At 2026-03-31 Blue Owl has 526 rows on both sides and 337 production only, 863 in all. All 337 are
the unfunded-commitment rows below.

## Unpublished basis (JV schedules), per fund

| Fund | Both | New only | Production only |
|---|---:|---:|---:|
| BCRED (Emerald, Verdelite) | 9,171 | 30 | 2 |
| Blue Owl (ORCIC Senior Loan Fund) | 1,416 | 0 | 0 |
| HPS (detached JV schedule) | 119 | 0 | 32 |

The global subsidiary-axis rule (Task 2) agrees with production: production marks all 1,416 Blue Owl
`ORCICSeniorLoanFundMember` rows `underlying_schedule` too.

## Causes

Counts are rows, both bases. `cause` is set in `cmp_row_set` by rules on row features, first match wins.

| Cause | Detail | Side | Rows | Funds |
|---|---|---|---:|---|
| old_wrong | production_build_lacks_filing | new only | 2,685 | Ares 1,408, Blue Owl 493, Apollo 784 |
| new_wrong | fair_value_in_filer_concept | production only | 1,955 | Blue Owl |
| new_wrong | ownership_pct_not_a_term_fact | production only | 258 | Ares |
| new_wrong | no_term_fact_but_position | production only | 99 published + 34 JV | Ares 44, BCRED 42+2, HPS 11+32, Blue Owl 2 |
| new_wrong | cash_axis_with_other_axis | production only | 8 | Apollo |
| new_wrong | cash_fund_not_recognised | production only | 1 | Apollo |
| needs_correction | correction_supplies_value_or_term | production only | 52 | Apollo 50, Ares 2 |
| needs_store_not_loaded | production_row_added | production only | 8 | Ares |
| needs_store_not_loaded | rate_only_context_pair | 2 production only + 2 new only | 4 | Ares |
| convention | cash_published_d7 | new only | 31 published + 30 JV | BCRED |
| not_yet_explained | none | new only | 1 | BCRED |

Totals: new_wrong 2,355; old_wrong 2,685; needs_correction 52; needs_store_not_loaded 12;
convention 61; not_yet_explained 1. One-sided rows: 5,166 (new only 2,749, production only 2,417).

### What was checked for each

**production_build_lacks_filing (2,685).** Rule: new only, the filing is the selected one, and
production has no rows at all for that fund and date. These are the three Q3-2026 10-Qs. Task 1
checked the filings are absent from `bdc_filings_index.csv` and from holdings. Opened: none; the
cause is structural. Called `old_wrong` because production is stale, not because it reads them
wrongly. Drops to 0 when production is rebuilt.

**fair_value_in_filer_concept (1,955).** Rule: production only, role `not_schedule` by rule 3, and
the context carries a fact named `*FairValue*` outside the us-gaap namespaces. All 1,955 are Blue Owl
contexts whose only value fact is `orcic:InvestmentOwnedFairValueNetOfUnamortizedFees` (with
commitment and financial-support facts). Opened 6 printed rows and the sibling contexts of 2 issuers:
they are unfunded revolver and delayed-draw lines ("Themis Solutions ... revolving loan", commitment
6,925, fair value (69)); the funded loan of the same issuer is a separate context both sides publish.
Production reads them because its `CONCEPT_MAP` matches the substring `investmentownedfairvalue`
(`pipeline/bdc_filings.py`). Evidence production is right: Blue Owl's filed total investments include
these values. Production ties to the filed total at every quarter 2024-12-31 to 2026-06-30; this layer
is over the filed total by exactly the sum of these rows each quarter (for example 2026-03-31:
+33,790,000 against -33,790,000 on 337 rows). 1,271 rows are 0, 684 negative.

**ownership_pct_not_a_term_fact (258).** Rule: production only, role `unresolved`, and the context
carries `InvestmentOwnedBalancePercentOfShares`. All Ares: limited partnership, member and LLC
interests (Ivy Hill, Senior Direct Lending Program, co-invest LPs). Opened 10 printed rows, all
schedule lines with an acquisition date and an ownership percentage. Ares's new-layer total is short
of the filed total by about 1.9 to 2.1bn in most quarters, chiefly Ivy Hill; production ties.
Checked the other way: 0 aggregates carry this fact, and the 14 unresolved Ares rows with it that
production does not have are all in the Q3-2026 filing.

**no_term_fact_but_position (133).** Rule: production only, role `unresolved`, reason "no term fact",
none of the rules above. Opened 8 Ares, 6 BCRED, 6 HPS, 2 Blue Owl, 8 JV-schedule rows. They are:
BCRED's own interests in Emerald JV and Verdelite JV and co-invest preferred units; HPS's ULTRA III
LLC interest; Ares zero-value undrawn revolvers (40) and LP interests whose units are untagged; one
Blue Owl LP interest and one unfunded delayed-draw line; HPS JV-schedule unfunded commitments tagged
with `QualifiedAffordableHousingProjectInvestmentsCommitment` and negative fair value. Evidence:
HPS's shortfall to the filed total equals the ULTRA III value in each of the 11 quarters from
2023-12-31 to 2026-06-30 (e.g. 2026-03-31: -426,214,000); BCRED's shortfall of 1.6 to 2.4bn a quarter is its Emerald and
Verdelite interests. Zero-value rows cannot be tested by the total.

**cash_axis_with_other_axis (8).** Rule: production only, role `not_schedule` by rule 1, context on
`CashAndCashEquivalentsAxis`. Apollo money-market funds (Goldman Sachs Financial Square, State Street)
on the cash axis plus the affiliation axis, with the value in the filer concept
`InvestmentOwnedAtFairValueAfterCashEquivalents`. Rule 8 takes the cash axis only when it is the sole
member, so rule 1 removes them. Opened 8 of 8. D7 says cash rows are positions.

**cash_fund_not_recognised (1).** Apollo "Goldman Sachs Financial Square Government Fund
Institutional" on an identifier context with no term fact. The money-market pattern does not match
it, so it is not cash and the cross-check holds it. Opened 1 of 1.

**correction_supplies_value_or_term (52).** Rule: production only and a loaded context-keyed value
correction names the context with fair value or a term field. Apollo 44: `wrapper:untagged_values`
fair value 0 (printed as a dash, no fact); Apollo 6 and Ares 2: untagged principal and cost. Opened
4 Apollo fair-value rows, 4 Apollo principal rows, 2 Ares rows: the printed number is there and not
tagged. Corrections are not applied in this slice.

**production_row_added (8).** Rule: production only and production's `corrected_fields` contains
`_row:added`. Ares 2025-03-31 and 2025-06-30, contexts on `InvestmentIssuerNameAxis` with no
identifier member. Store: `data/overrides/agent_investigate_rules/1287750/`
`recover_2025q1_values_tagged_on_issuer_axis.json` (c-1033, c-1491, c-1679, c-1699) and
`recover_2025q2_values_tagged_on_issuer_axis.json` (c-1171, c-1590, c-1729, c-1750). Read both; all 8
match. Opened 8 printed rows: real loans and units. Slice 1 lists this store as not loaded.

**rate_only_context_pair (4).** Rule: a one-sided row whose same-accession, same-label twin is
one-sided on the other side, where the production row carries rate facts and no fair value, and the
filer has an unloaded `rate_only_contexts` declaration. Ares "Expereo USA, Inc. and Ristretto Bidco
B.V." at 2025-03-31 (c-1727 / c-1728) and 2025-06-30 (c-1775 / c-1776). Both sides have the
position; production keys it to the rate context, this layer to the value context. Declaration:
Ares wrapper `rate_only_contexts: adopt_adjacent` (`pipeline/source_encodings.py`
`adopt_rate_only_contexts`). This is the case open in spec section 11; it is explained. Opened all 4
and their 4 neighbouring contexts. Note: the code's docstring says the value context is kept and the
rate context removed; production's rows carry the rate context id. Not followed up.

**cash_published_d7 (61).** Rule: new only, and the row is cash or its label names a cash-equivalent
fund (production's own keywords, plus "cash management"). BCRED State Street, Fidelity, Dreyfus and
BlackRock money-market or liquidity funds, 31 in the fund's schedule and 30 in its JV schedules. All
61 labels read. Production drops them: `bdc_xbrl_wrapper.py` `non_private_markers` treats
money-market names as non-positions. D7 publishes them. 10 of the 61 are not flagged `is_cash` here
(Dreyfus Treasury Obligations Cash Management, BlackRock Select Treasury Based Liquidity Fund, Morgan
Stanley Euro Liquidity Fund): the role agrees with D7, the cash flag does not.

**not_yet_explained (1).** BCRED 2025-06-30 c-1259, "Box Co-Invest Blocker, LLC - (BP Alpha
Holdings, LP) - Class C Preferred Units", fair value 0, cost 390,000, 1 share. Production has the
same line in every other quarter from 2023-09-30 but not this one. That quarter the JV rows are
labelled "... Class C Preferred Units 1, Emerald JV LP" and "... 2"; production may treat c-1259 as
their parent. Production code not checked, so not named.

## Unresolved rows from Task 2 (974) against production

| Fund | Production publishes | Production JV schedule | Production leaves out | Production lacks the filing |
|---|---:|---:|---:|---:|
| Ares | 304 | 0 | 148 | 54 |
| BCRED | 42 | 2 | 2 | 0 |
| Blue Owl | 2 | 0 | 56 | 18 |
| Apollo | 7 | 0 | 296 | 0 |
| HPS | 11 | 32 | 0 | 0 |
| Total | 366 | 34 | 502 | 72 |

All 120 Apollo rollups whose fair value matches their children and cost does not are among the 296
production leaves out. No production row is an aggregate here: production also leaves out all 1,624
aggregates, including the 22 subtotals only the one-pass rule passes.

## Filing selection (Task 1)

74 of 79 fund-quarters select the same accession as production. The differences are the three
Q3-2026 filings production has not loaded and two cover-only filings refused (BCRED 2022-06-30, HPS
2022-12-31) where production has no rows either. Differs: 0.

## Baseline tests

| Test | Count | Ceiling |
|---|---:|---:|
| baseline_cmp_row_set_new_only (both bases) | 2,749 | 2,749 |
| baseline_cmp_row_set_production_only (both bases) | 2,417 | 2,417 |
| baseline_cmp_row_set_not_yet_explained | 1 | 1 |
| baseline_cmp_row_set_no_context | 0 | 0 |

Also: `cmp_row_set_key_and_cause` (key unique; no cause on a matched row; every one-sided row has a
cause from the list) and column tests in `_intermediate.yml`.

## Not checked

- Value fields on matched rows (slice 3), beyond the fund totals above.
- Why production dropped the Box Co-Invest row.
- Whether unfunded-commitment rows (Blue Owl, HPS JV) should be positions at all. Production
  publishes them and the filer's total includes them; that is not an owner decision.
- The 1,413 label-keyed corrections (no context id) are not used by the cause rules. One Ares row
  in `no_term_fact_but_position` (Merit Financial, shares untagged) has one.
- The stores `bdc_aggregate_row_overrides.json` (Ares entries are all exclusions; none touches a
  one-sided row) and `bdc_xbrl_html_section_bridges/` (HPS proposed file only) were read, not
  matched entry by entry. The wrappers' `dispatch` sections were not read.
- The cash-fund keyword rule could match a company named, for example, "... Cash Management LLC". It
  applies only to one-sided rows; no such case today.
- Funds outside the five.
