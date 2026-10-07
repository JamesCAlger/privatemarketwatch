# v0.5 decision log (autonomous run, 2026-10-06 onward)

Scope: the five v0.5 funds, 2022 to Q1 2026. Authority: the owner said in session on 2026-10-06
"I give permissions" in reply to four requested permissions: (1) repair a rule that fires by
construction, shown from the data; (2) accept my own disposition when a re-runnable check supports
it; (3) decide whether presence signals count as outstanding; (4) change shared code on five-fund
evidence. I am treating them as granted for this run only. Limits kept: no downloads, no 70-fund
rebuild, no writes to published data, no push.

Each entry: what was decided, the evidence, how to re-run it, what it does not cover, and the
commit. A decision here was made by an agent without independent review. Reverse one by reverting
its commit.

Reference for "correct": `docs/production_stack/02_data_contract.md`.

## Rule repairs

### D-001 E07 counts source positions, not every wrapper leaf

- **Decision.** `check_E07_position_count_vs_filing` counts a source row when the reconciliation
  status is `matched`, `value_mismatch`, `diagnostic_field_mismatch` or `missing_from_pipeline`.
  Without a status column it keeps the wrapper-leaf count.
- **Evidence.** Sandbox `five8`, 2026-03-31: Ares 2,898 comparative-period rows and 1,456 rows
  collapsed as a second dimension path beside 1,419 positions and 1,419 output rows; HPS 848
  comparatives beside 835 and 835; BCRED 4,078 and 2,016 beside 2,006 and 2,006. The rule failed
  in all 62 fund-quarters.
- **Re-run.** `python scripts/v05_evidence/e07_probe.py five8 2026-03-31`.
- **Not covered.** The rule still fails when over 10 pct of positions are missing from, or extra
  in, the output (tests). It no longer notices a wrapper that classifies no leaves.
- **Applies to** every fund. Checked on the five.

### D-002 A07 skips a fund-quarter that reports no percent of net assets

- **Decision.** `check_A07_pct_of_net_assets_sum` returns `skip` when no row of the fund-quarter
  has a reported percent.
- **Evidence.** Ares, Apollo and HPS tag `InvestmentOwnedPercentOfNetAssets` per industry or
  category only (latest filings: 51, 127 and 266 facts against about 1,400, 770 and 830
  positions; 0 source rows with a percent). Blue Owl stopped per-position tagging at 2025-03-31.
  46 findings.
- **Re-run.** `python scripts/v05_evidence/pctq.py five8 <cik>`.
- **Not covered.** A fund-quarter with some reported percents summing out of range still fails
  (test). A filer that stops tagging is no longer flagged by this rule; nothing else flags it.
- **Applies to** every fund.

### D-003 B02 flags a repeated fact, not two positions that share a key

- **Decision.** `check_B02_unique_position_keys` treats two rows as duplicates only when they
  also share accounting scope, maturity, rates, spread, principal, units and fair value.
- **Evidence.** 1,485 repeated keys in the five funds; none has the same identifier and values;
  every row has its own `position_id`. Apollo 441: tranches whose key drops rate and maturity.
  BCRED 607 and Blue Owl 420: the same name in the fund's schedule and the JV's, or several loans
  under one bare issuer name. 31 findings.
- **Re-run.** `python scripts/v05_evidence/b02.py five8`.
- **Not covered.** Unique position ids remain J04's test. Two different loans with identical terms
  and value would now be flagged as a repeat; that is rare and worth a look when it happens.
- **Applies to** every fund.

### D-004 HTML-extraction checks apply only where that extraction feeds published rows

- **Decision.** `html_agg` and `html_carry` report `skip` for a fund-quarter whose published BDC
  rows all come from the XBRL lane.
- **Evidence.** The published file has 563,423 `xbrl_field` rows, 179 rule-added rows and none
  from the HTML lane. Of 2,225 fund-quarters in `html_template_validation.csv`, 458 have published
  rows (all XBRL) and 1,711 have none. Ares 2024-03-31: HTML extraction 129.6B against 23.1B
  filed. 24 findings.
- **Re-run.** `python scripts/v05_evidence/html_lane.py`.
- **Not covered.** Fund-quarters with no published rows keep their result. The HTML extraction
  itself is still wrong for those Ares quarters; nothing published depends on it.
- **Applies to** every fund.

### D-005 The principal range check applies its dollar cap to dollars

- **Decision.** `fmt_principal_amount` applies the 100 billion upper bound only when the
  principal currency is USD or unstated. `fmt_principal_amount_usd` is unchanged.
- **Evidence.** Apollo, Delivery Hero Finco Germany, eight quarters: principal 194,831,194,000
  Korean won, about 128M to 148M dollars beside a fair value of 126M to 149M. Contract H03:
  principal stays in the loan's currency.
- **Re-run.** `python scripts/v05_evidence/weakrows.py five8 1837532`.
- **Not covered.** Ares 2022-09-30 SDLP certificates (269.8B dollars filed) still fails both
  checks: see D-012.
- **Applies to** every fund.

### D-006 X06 reads the unfunded marker from the whole row text

- **Decision.** X06's exemption for revolvers, delayed draws and commitments uses the shared
  `_unfunded_position_sql()` (issuer name, instrument text, identifier), not the issuer name alone.
- **Evidence.** The rule already meant to exempt these. Apollo 158 of 184 and Blue Owl 7 of 9 rows
  with principal over ten times fair value are named revolver or delayed draw in the identifier.
  Splitting Ares and Apollo issuer names from the instrument (this week) removed the wording from
  the one field the rule read.
- **Re-run.** `python scripts/v05_evidence/unfunded.py five8`.
- **Not covered.** HPS and BCRED identifiers carry no instrument wording, so their unfunded lines
  still fire: see D-010. A ratio cut was rejected: it would also hide the Ares SDLP error (0.4 pct).
- **Applies to** every fund.

### D-007 The gross-asset reconciliation adds filed cash when the holdings hold cash rows

- **Decision.** `check_gav_reconciliation` adds `cash_equivalents_at_fair_value` to filed
  investments for a fund-quarter whose holdings include a cash-class row.
- **Evidence.** Apollo: the residual equals the cash rows to the dollar (2025-06-30 785,933,000;
  2025-09-30 407,439,000; 2025-12-31 227,502,000). The conservation engine already compares this
  way (`companyfacts_fv_plus_cash`). 12 findings (gav_reconciliation, F20, GAV_BDC02).
- **Re-run.** `python scripts/v05_evidence/gav.py five8 1837532`.
- **Not covered.** With cash rows and no filed cash figure the excess still shows (test).
- **Applies to** every fund.

### D-008 C107 (negative cost) is not repaired

- **Decision.** Left as is. The 35 findings are dispositioned instead (D-010).
- **Reason.** The rule's own comment records that excluding negative-value rows lost 5 of 8
  adjudicated real errors elsewhere in the cohort, and says not to try a row-level cut again
  without new evidence. I have none for the other funds.

### D-009 Standing dispositions are read by the findings ledger

- **Decision.** New store `data/overrides/finding_dispositions/` and module
  `pipeline/finding_dispositions.py`. An unresolved finding covered by an entry gets a terminal
  state `dispositioned_informational`, `dispositioned_as_filed` or `dispositioned_not_applicable`;
  the acceptance check and the fund sandbox count those as resolved.
- **Why a new store.** Verdict files live under `data/output` and are keyed by review id. A
  disposition has to be version-controlled and keyed by what the finding is (fund, engine, rule,
  quarter).
- **Limits built in.** Every entry needs evidence and a re-run command. `as_filed` and
  `not_applicable` must name their funds and their quarters, so a new quarter or another fund is
  reviewed again. Only `informational` may cover every fund and quarter. A reviewer's earlier
  "real error" verdict is left standing unless the entry is informational or carries filing
  evidence and says so explicitly. An unreadable entry raises; it is never skipped.
- **Not covered.** No automatic check yet re-tests an entry's evidence when a new build runs.

### D-010 The coupon-unresolved tag is written only when a rate was filed

- **Decision.** The finalizer writes `interest_rate:coupon_unresolved` when a filed rate exists
  and cannot be read as all-in. A row that files no rate is not tagged.
- **Evidence.** Sandbox `five8`: 24,385 rows tagged in the five funds; 24,370 file no rate (all
  8,887 Blue Owl rows, which tags no rate at all). The other 15 (13 Ares, 2 Apollo) file a rate
  below their PIK rate and stay tagged. `financial_convention_unresolved` fired in all 69
  fund-quarters.
- **Re-run.** `python scripts/v05_evidence/unresolved_why.py five8`.
- **Not covered.** A loan with no filed rate is still visible through X02, C01 and dl_rate_fill.
- **Applies to** every fund.

### D-011 A published row whose values did not change is not a prior-period row

- **Decision.** The purity check takes the latest matching source period, not the earliest.
- **Evidence.** HPS 2025-03-31, Calabrio, Inc. 1: identical value, cost and principal in the
  2024-12-31 and 2025-03-31 contexts; the published row is context c-562 (2025-03-31). PP03 fired
  in 46 fund-quarters on one to eight such rows each.
- **Re-run.** `python scripts/v05_evidence/row.py five9 1838126 2025-03-31 "Calabrio, Inc. 1" 4`.
- **Not covered.** A published row found only in a prior period is still flagged (test).
- **Applies to** every fund.

### D-012 Rate-fill checks measure funded loans

- **Decision.** C01 and `dl_rate_fill` count loan rows with fair value above zero.
- **Evidence.** Sandbox `five9`: on all loan rows Blue Owl is under 80 pct in 6 quarters and HPS
  in 7; on funded rows the lowest fill is 93.4 pct and 92.2 pct and no quarter is under 80. The
  gap is undrawn revolvers and delayed draws filed at zero or a small negative value with no rate
  (HPS 1,084 such rows, Blue Owl 1,634). 23 findings.
- **Re-run.** `python scripts/v05_evidence/ratefill.py five9`.
- **Not covered.** A fund whose funded loans lack rates still fails (test).
- **Applies to** every fund.

### D-013 "Equity investment" is an equity keyword

- **Decision.** `equity investment` added to the equity keywords of the instrument classifier.
- **Evidence.** Blue Owl, 2025-12-31 and 2026-03-31: "Specialty finance equity investment" rows
  tagged with a principal and no units were classed LOAN / DIRECT_LENDING by the field heuristic
  (6 rows, 936M); the same wording with units was already EQUITY_COMMON (15 rows, 2.0B).
- **Re-run.** `python scripts/v05_evidence/owl_class.py five9`.
- **Not covered.** Loan keywords are still tested first, so a row naming a loan stays a loan.
  "Specialty finance debt investment" with units and no principal is still classed equity.
- **Applies to** every fund. Not checked outside the five; rows elsewhere that contain the phrase
  and were classed by the field heuristic will change class.

### D-014 The percent identity reads published rows and allows for rounding

- **Decision.** `pct_of_net_assets_identity` excludes JV-schedule rows and passes a row within
  0.06 percentage points as well as within 10 pct of fair value.
- **Evidence.** Sandbox `five10`: BCRED 11,749 rows outside the band, of which 8,387 are JV
  rows (their percent is of the JV's net assets), 3,348 are filed as 0.0 or 0.1 and 14 are other;
  Blue Owl 2,458: 1,397 JV, 541 at the rounding floor, 520 other with a median gap of 0.039
  points. 23 findings.
- **Re-run.** `python scripts/v05_evidence/ident_c04.py five10`.
- **Not covered.** A percent ten times too large still fails (test). A wrong percent on a
  position smaller than about 0.06 pct of net assets is no longer detectable by this rule.
- **Applies to** every fund.

### D-015 The rate-stability check needs a sample

- **Decision.** D07 compares two quarters only when each has at least 30 rated rows.
- **Evidence.** Apollo files spreads, not rates: 13 rows carried a rate at 2023-09-30 (median
  6.5) and 15 at 2023-12-31 (median 9.75), out of 237 and 283. 1 finding.
- **Re-run.** `python scripts/v05_evidence/ratemed.py five11 1837532`.
- **Not covered.** A shift across a full schedule still fails (test). For a fund with few rated
  rows the check is now silent.
- **Applies to** every fund.

## Row corrections

### D-016 Apollo, Material Holdings term loan, 2024-12-31: spread 16.0 corrected to 6.1

- **Decision.** One entry in `data/overrides/row_corrections.csv`.
- **Evidence.** Filing 0000950170-25-038785, context C_6237440e-e6ad-460e-909b-c200abfa03f3: the
  spread fact is 0.16; the printed line for the same position reads "S+610 (Includes 8.03% PIK)";
  the sibling tranche of the same loan is tagged 0.061. A reviewer had already marked the finding
  a real error.
- **Re-run.** `python scripts/v05_evidence/row.py five11 1837532 2024-12-31 "Material+ Material Hold" 3`.
- **Not covered.** The correction is keyed to this filing and row; it does not carry forward.

## Rate published from the PIK tag

### D-018 Ares: a loan filed with only a PIK rate takes it as its coupon

- **Decision.** New wrapper setting `source_encodings.pik_only_tag_reading: ["coupon"]`, set for
  Ares only. For such a fund a loan with a PIK rate, no plain rate and no spread publishes the
  PIK rate as `interest_rate` (kind all-in, transform `interest_rate:pik_only`).
- **Evidence.** Ares 10-Q for 2025-06-30, coupon column: WebPT senior subordinated loan
  "13.25 % PIK", Amerivet subordinated loan "16.50 % PIK"; tags carry only
  `InvestmentInterestRatePaidInKind`. Reviewers cited the same pattern in six Ares quarters
  (22 HoldCo "12.96 % PIK", ADG "6.56 % PIK"). 257 Ares rows over 15 quarters.
- **Why a separate setting.** HPS reads its plain tag as all-in too, but its PIK tag on such rows
  holds a margin: Daphne S.P.A. is printed "E + 6.75 %" with a coupon of 8.75 % and tagged PIK
  0.0675. A first version keyed on the plain-tag reading would have published 6.75. Caught by
  checking HPS's printed schedule before the run.
- **Re-run.** `python scripts/v05_evidence/pikonly.py five12`;
  `python scripts/v05_evidence/filing_grep.py 1287750 000128775025000038 html "WebPT, Inc." 12 330`.
- **Not covered.** Only four Ares lines were read on the printed page. An Ares loan with a cash
  coupon left untagged and a PIK tag present would be published too low; none was seen.
- **Guards changed with it.** Loan rows only (Ares equity units printed with a PIK dividend
  keep no rate). The final schema check refused the first build (1,038 rows with a rate and no
  filed plain rate); it now accepts such a row only when it carries the transform and equals
  `pik_rate`. The provenance re-verifier checks the coupon against the PIK fact in the filing.
- **Result.** Sandbox `five13`: 257 Ares loan rows publish a coupon from the PIK tag.

## Standing dispositions

### D-017 Dispositions written to `data/overrides/finding_dispositions/v05_2026-10-06.json`

Generated by `python scripts/v05_evidence/make_dispositions.py five11 --write`. The fund-quarters
of each as-filed or not-applicable entry are the ones with an unresolved finding in sandbox
`five11`; nothing else is covered. Each entry carries its evidence and re-run command.

| Id | Class | Rule | Funds | What it says |
|---|---|---|---|---|
| DS-001 | informational | nonaccrual_flag | all | Reports that a loan is on non-accrual; a credit fact |
| DS-002 | informational | text_pathway | all | Records that a value was read from row text |
| DS-003 | not applicable | F28 | all five | Fund-level figures for quarters with no cached schedule |
| DS-004 | as filed | C107 | Blue Owl to 2024-09-30, HPS | Negative cost filed on undrawn lines |
| DS-004A | as filed | C107 | Apollo | The same; replaces two reviewer verdicts whose own quotes show the printed negative cost |
| DS-004B | not applicable | C107 | Blue Owl from 2024-12-31 | Cost on commitments-table rows is the pipeline's labelled proxy; no cost is filed |
| DS-005 | as filed | X06 | all five | Principal far above value: commitments and markdowns |
| DS-006 | as filed | X02 | BCRED, Blue Owl, HPS | No rate or spread fact is tagged for these rows |
| DS-007 | as filed | C103 | HPS, Apollo | Small negative values on undrawn lines |
| DS-008 | as filed | maturity_not_past | Apollo | Heubach loan filed with a past maturity; replaces a reviewer verdict |
| DS-010 | as filed | B01 | Apollo | Contexts with no value fact |
| DS-011 | as filed | C04 | HPS, Blue Owl | Equity rows filed without units |
| DS-013 | as filed | merged_context_excluded | Ares | Rows the filer spread over several contexts |
| DS-014 | as filed | FX01 | Apollo | Principal in a currency code with no rate (KPW) |
| DS-015 | as filed | financial_convention_unresolved | Ares, Apollo | Filed rate below the PIK rate; published rate left empty |
| DS-016 | not applicable | SRC_BDC01 | Ares, Blue Owl, Apollo | Issuer-level and subtotal source rows read as missing positions |
| DS-017 | not applicable | parser mismatch | Ares, Blue Owl | The same rows, second engine |
| DS-018 | as filed | SRC_BDC02 | Ares | Eight restored positions whose values sit on the issuer-name axis |
| DS-019 | as filed | anchor_missing | Ares | The same eight positions |
| DS-020 | as filed | pct_of_net_assets_identity | BCRED, Blue Owl | One to five rows a quarter with a filed percent that disagrees with value |
| DS-021 | as filed | income_identity | HPS, Blue Owl | Net investment income is after fee waivers; expenses are gross |
| DS-022, DS-023 | as filed | fmt_principal_amount(_usd) | Ares | SDLP principal filed as 269.8 billion |
| DS-024 | not applicable | PP03 | Blue Owl | Current-period row whose rescaled units equal the prior period's |

### D-019 Dispositions withdrawn or narrowed after reading the reviewers' verdicts

The first version of the store left 20 findings open, each with an earlier reviewer verdict of
"real error". Reading those verdicts (`python scripts/v05_evidence/verdicts.py five12`) showed
that several of my entries for the neighbouring quarters were wrong.

- **DS-012 (X01, equity with a rate) withdrawn.** I had called these common units filed with a
  stated rate. The reviewers quote the printed lines: HPS OneTeam is "Preferred Units 8.00 %"
  (the tag says "Class D Units"); BCRED GTCR Investors A-1 Units sits under First Lien Debt with a
  spread, maturity and par; BCRED Huntington Bancshares is a bond. These are classification
  errors. 9 findings stay open.
- **DS-009 (X07, Amergin) withdrawn.** The row is an equity stake classed as a credit fund
  interest because the issuer name contains "Asset Management". A classification error. 4 open.
- **DS-006 (X02, no rate) narrowed to BCRED, Blue Owl and HPS.** For Ares the PIK-only rows are
  now published (D-018), and at least one funded loan has its rate filed under a differently
  spelled member (Apex Service Partners, 2023-12-31: values on context c-1206, rate 12.40, PIK
  2.00 and spread 7.00 on c-1205 with no values). For Apollo one bond prints its rate in the row
  text with no tag (Genmab, "Corporate Bond 6.25%", 2025-12-31). Ares and Apollo stay open.
- **DS-004 (C107, negative cost) split.** Blue Owl's rows from 2024-12-31 come from the
  commitments table, which files no cost; the published cost is a proxy. See DS-004B.

## Second batch: the 35 open findings (owner: "Fix the remaining 35")

### D-020 Ares: rate facts on a neighbouring context join their value row

- **Decision.** New wrapper setting `source_encodings.rate_only_contexts: ["adopt_adjacent"]`, set
  for Ares. In staging, a context with rate facts and no value, cost or principal gives its rate,
  spread and PIK to the value row with a principal and no rate facts when the two contexts are
  adjacent, share the first 16 letters and digits of the identifier and have no other candidate.
  The joined fields are named in `src_filled_fields`; the rate-only row is removed.
- **Evidence.** Five pairs in 15 quarters (200.5M). Apex Service Partners 2023-12-31: value on
  c-1206, rate 12.40, PIK 2.00, spread 7.00 on c-1205; printed "12.40 % (2.00 % PIK) SOFR (Q)
  7.00 % ... 148.5 148.5 144.8". Aventine 2025-06-30: PIK 10.25 on c-1267 under "Senior
  subordinated loan", value on c-1268 "Second lien senior secured loan"; printed "Second lien
  senior secured loan 10.25 % PIK ... 50.6 50.6 41.0".
- **Correction to the first batch.** I wrote that about 35 funded Ares loans (820M) had rates
  filed under another member. Wrong: five do. The rest have no rate fact and the printed page
  shows none (non-accrual, footnote 9); see DS-006A.
- **Re-run.** `python scripts/v05_evidence/orphan_pairs.py five13 1287750`.
- **Not covered.** Three of the five pairs were read on the printed page. Filings whose context
  ids carry no number (2022-09-30 to 2023-03-31) cannot pair.

### D-021 Row corrections from the printed schedule (13 rows, 31 field values)

Written by `python scripts/v05_evidence/make_row_corrections.py five13 --write` to
`data/overrides/row_corrections.csv`. `asset_category` and `issuer_category` were added to the
fields that store may correct, so a class correction moves the category with the index class.

| Fund, quarter | Row | Change | Printed evidence |
|---|---|---|---|
| Apollo 2026-03-31 | Rocket Youth delayed draw | fair value -1,884,000 to 1,884,000 | "2,047 2,013 1,884"; issuer subtotal 11,000 |
| Apollo 2026-03-31 | SavATree delayed draw | fair value 248,000 to -248,000 | "- ( 44 ) ( 248 )"; issuer subtotal 16,538 |
| Apollo 2024-06-30, 2024-09-30 | Paymentsense term loan | filed rate 0.125 to 12.5 | row text "Interest Rate 12.50% (includes 6.25% PIK)" |
| Apollo 2025-12-31 | Genmab corporate bond | rate empty to 6.25 | "Corporate Bond 6.25 %" |
| BCRED 2022-12-31 | Huntington Bancshares (JV schedule) | common equity to loan | Bonds section, 4.44 %, 8/4/2028, par 620 |
| BCRED 2023-09-30 | GTCR Investors A-1 Units (JV schedule) | common equity to loan | under First Lien Debt, SOFR + 3.00 %, 9/20/2030 |
| HPS 2025-12-31, 2026-03-31 | OneTeam Partners units | common to preferred equity | "Preferred Units 8.00 %" |
| Blue Owl, four quarters | Amergin Asset Management units | credit fund interest to common equity | under Equity Investments, Class A Units, cost 1 |

- **Apollo 2026-03-31 total.** The two sign errors are the whole 3,272K gap (3,768 - 496).
  Found by comparing printed industry totals with published rows
  (`python scripts/v05_evidence/apollo_industry_totals.py five13 000119312526215667 2026-03-31`).
  Published now equals the printed total in all 13 Apollo quarters.
- **Also:** `pik_only_tag_reading` set for Apollo: Material Holdings 2024-09-30 reads "Interest
  Rate11.45% PIK" in its row text. One row.
- **Not covered.** Each correction is tied to one filing and row and does not carry forward.
  Amergin is classed the same way in quarters where no check fired; those are not corrected.
  The two BCRED rows are in a JV's schedule and are not published.

### D-022 Last dispositions, and drafted fixes

- **A drafted fix is not a resolution.** A finding with a fix that was staged or pulled by an
  earlier run, and never promoted, is now closed by a disposition only if the entry carries filing
  evidence and says it replaces the earlier verdict (`pipeline/finding_dispositions.py`). Four
  findings were in that state.
- **New entries.** DS-006A (Ares X02: no coupon printed or tagged), DS-006B (Apollo X02: Spirit
  Aerosystems loan filed with no rate), DS-012 restored for Ares and for HPS before 2025-12-31
  (equity units printed with a coupon), DS-025 and DS-026 (Apollo 2026-03-31: the reconciliation
  compares the two corrected rows with their wrongly signed tags). DS-010 now covers Apollo
  2026-03-31. DS-013 covers the rows joined under D-020.
- **Generator fix.** `make_dispositions.py` rebuilt the store from unresolved findings only, so a
  second run dropped every entry whose finding was already closed. It now keeps them.

### D-023 BCRED: the four quarters above the filed total

No rule flagged these, so they were not among the 35. Traced because they were the last known
gap between published and filed totals.

- **Three quarters: JV rows with misspelled labels.** Rows of a JV's own schedule are recognised
  by the label after the borrower's name. The filer misspelled it on a few rows: "Anticimex, Inc. ,
  Emerald JV LP2", "Java Buyer, Inc, Emerald JV LP. 2", "Howden Group Holdings Limited, Verdelite
  JV 2LP 1". Those rows were published as the fund's own. The label match now accepts an ordinal
  fused into the label, in the comma form only (`pipeline/source_encodings.py`).
  Evidence: the fair values that do not appear in the fund's printed schedule are exactly these
  rows and sum to the excess: 2023-09-30 three rows 9,506K; 2023-12-31 three rows 10,573K;
  2024-12-31 four rows 43,002K.
  Re-run: `python scripts/v05_evidence/unprinted_values.py five14 1803498 000180349825000021 2024-12-31 "Total Investment Portfolio 68,985,671"`.
- **One quarter: a footnote figure.** 2024-06-30: "$ 54.2 million of the cost and $ 35.6 million of
  fair value of WHCG Purchaser III, Inc. is considered to be on non-accrual status" is tagged on
  the issuer's name and was published as a position (35,600K, the whole excess). New rule file
  `data/overrides/agent_investigate_rules/1803498/exclude_footnote_figures_tagged_on_issuer.json`:
  no principal, units, rate or percent of net assets, and cost and value in round 100,000s. It
  selects that one row in 15 quarters.
  Re-run: `python scripts/v05_evidence/bcred_footnote_rows.py five14`.
- **Not covered.** The label change applies to any fund that sets
  `reporting_entity_identifier_suffixes`; BCRED is the only fund that does. The new rule file, like
  the others written this week, bypasses the fleet promotion gate.

## State after the second batch

Sandbox `five15` (after D-023): 305 findings for the five funds from 2022 on, 0 outstanding. 277 are
closed by a recorded disposition (159 as filed, 73 informational, 45 not applicable), 27 by an
earlier reviewer's false-alarm verdict, 1 by a promoted fix. Published equals filed within 0.5M
in 69 of 69 fund-quarters (`python scripts/v05_evidence/summary.py five15`). Excluding the BCRED
footnote rows made the reconciliation read them as missing positions; DS-027 and DS-028 record why
they are not.

Zero outstanding is not "data correct". Known and recorded, not fixed:

- Ares SDLP principal 269.8 billion at 2022-09-30, as filed (DS-022).
- HPS and Blue Owl: `pik_rate` holds a margin on loans whose coupon is a PIK margin; those rows
  have no rate or spread (DS-006). Blue Owl publishes no rate on any credit row.
- Blue Owl undrawn lines from 2024-12-31 carry a proxy cost (DS-004B).
- Ares Redwood Series D units (60.5M): tagged rate kept, printed line not found by search.
- Ares non-accrual loans: three issuers read on the printed page out of 14 to 30 rows a quarter.
- Ledger rows dated before 2022 or for other funds (several thousand, most from the production
  verdict store) are outside this scope and untouched.

Weakest dispositions, for the owner's attention:

- **DS-022 and DS-005 (Ares 2022-09-30).** The published principal of 269.8 billion is wrong. It
  is what the fund filed, in the tag and on the printed page. Cost and value are 1,121.0M and in
  other quarters principal is at or near cost, so 1,121.0M is the likely figure, but no filing
  says so. Left as filed; a sum of Ares principal for that quarter is overstated by about 268.7B.
- **DS-004B.** Whether a proxy cost should be published at all on an undrawn line is not settled
  here. The entry only records that the rule's test of filed cost does not apply.
- **DS-006.** For HPS and Blue Owl the printed schedule shows a margin or coupon on PIK loans
  that the tags do not carry as a spread or rate. The published fields follow the tags, so
  `pik_rate` holds a margin for some of these rows.
- **DS-003.** Whether schedules exist on EDGAR for the earlier quarters was not checked.
- **DS-021.** `total_expenses` holds gross expenses. Whether it should hold net expenses is a
  schema question this entry does not settle.
- **DS-010.** "Tagged under two spellings" rests on the published total matching the filed total,
  not on a row-by-row trace.

## Owner rulings, 2026-10-06 (in session, after the second batch)

- **Dispositions accepted.** Owner: "i accept your dispositions". Covers the 50 entries in
  `data/overrides/finding_dispositions/v05_2026-10-06.json` as committed at 27f106f.
- **Nothing goes to production for now.** No rebuild of published data, no push.
- **Permissions are not standing.** The four permissions of this run ended with it; ask again
  next session.
- **Open with the owner:** the data choices listed in the session (SDLP principal, PIK margin in
  `pik_rate`, proxy cost on undrawn lines, gross `total_expenses`, rule files outside the gate).

## Data choices ruled by the owner, 2026-10-06 ("go with your recommendations")

Sandbox `five16` after these: 300 findings, 0 outstanding; published equals filed within 0.5M in 69
of 69 fund-quarters. Nothing was rebuilt for production.

### Ares SDLP principal: kept as filed

No change. DS-005, DS-022 and DS-023 stand.

### D-024 A negative first value is not a proxy cost

- **Decision.** `cost_proxies` gives no proxy when the first observed value is negative. The cost
  stays empty and the audit method is `no_source_valid_donor`.
- **Narrower than recommended.** I recommended "zero or negative". An existing test
  (`test_unrelated_field_correction_does_not_disqualify_observed_zero_fv`) keeps an observed zero
  as a cost of zero on purpose, so zero still donates. One existing test that expected a negative
  proxy (a foreign value of -80 converting to -120) was changed to expect no cost.
- **Result.** Blue Owl: the 508 negative proxy costs are gone; DS-004B has nothing left to cover.
  Three small negative-value rows with no cost, previously hidden by the proxy, now show (Blue Owl
  Jellyfish -0.09M; HPS FH BMX -0.15M and Brandt -0.10M) and are added to DS-007.
- **Re-run.** `python scripts/v05_evidence/negcost.py five16`.
- **Applies to** every fund. Not checked outside the five.

### D-025 `net_expenses` added to the fund-level table

- **Decision.** New field `net_expenses` (tag
  `InvestmentCompanyExpenseAfterReductionOfFeeWaiverAndReimbursement`). `total_expenses` stays
  gross. The income identity compares net expenses where filed.
- **Found while doing it.** In a 10-K quarter the income table's figures (`total_investment_income`,
  `total_expenses`, `net_investment_income`) are the annual amount divided by four
  (`pipeline/bdc_fund_income.py`, "Annual -> quarterly"), not the fourth quarter. HPS 2023-12-31:
  gross expenses 104,167,750 is 416,671,000 / 4; the true quarter is 127,460,000. `net_expenses`
  comes from the other extraction path and is the true quarter. The identity therefore compares
  gross when net exceeds gross. The divide-by-four is not changed here.
- **Not covered.** Blue Owl files only the offset (`InvestmentCompanyExpenseOffsetArrangement`),
  not a net figure, so its 2022-03-31 gap stays under DS-021. A fund whose waiver is small will
  not show the difference at all.
- **Re-run.** `python scripts/v05_evidence/netexp.py five16 1838126`.

### D-026 HPS: a PIK tag that is a margin is published as the spread

- **Decision.** `pik_only_tag_reading` admits `["margin"]`, set for HPS. On a loan with a PIK
  rate, no plain rate, no spread and a known reference rate, the PIK figure is published as
  `basis_spread` (transform `basis_spread:pik_margin`). `pik_rate` keeps the filed number.
- **Evidence.** HPS 10-K for 2024-12-31: Southern Graphics Inc. "SF + 7.50 % PIK", Foundation
  Automotive "SF + 7.75 % PIK"; 10-Q for 2026-03-31: Daphne S.P.A. "E + 6.75 %". 60 rows (57 SOFR,
  3 EURIBOR). Rows with no reference rate are left alone: Wildcat Car Wash is "15.00 % PIK", a
  fixed coupon, and Aesthetics Australia is "B + 9.38 % PIK" with a reference the parser does not
  know.
- **Not done for Blue Owl.** Its PIK-only rows carry no reference-rate tag, so a fixed 12 % and an
  "S+ 5.75 %" margin cannot be told apart from the tags. It needs the "Ref. Rate" column from the
  printed page. 247 rows stay as they were. Blue Owl rows with both a spread and a PIK figure
  carry the cash margin in `basis_spread` and the PIK margin in `pik_rate`; their total margin is
  the sum, and nothing publishes it.
- **Re-run.** `python scripts/v05_evidence/hps_pik_margin.py five16`.

### D-027 Rule files and row corrections: acceptance record

- **Decision.** `docs/investigations/v05_rule_acceptance.md` lists the nine rule files and the row
  corrections written this week with content hashes and evidence, under the owner's ruling to
  accept them without the fleet gate.
- **Not done.** The live `admission_manifest.json` was not created. It would change how all 139
  rule files of every fund load, and the owner asked for nothing to reach production for now.

## 2026-10-07: Blue Owl reference rate read from the printed column (owner: "read the ref rate column for blue owl")

### D-028 Blue Owl: the printed reference-rate column is read, and a PIK margin over it is the spread

- **Decision.** Blue Owl's wrapper names its reference-rate column (`reference_rate_columns`:
  "Interest", "Ref. Rate") and two codes the shared table lacks (`reference_rate_codes`: SR=SOFR,
  SA=SONIA), and sets `pik_only_tag_reading: ["margin"]`. The inline field-status reader treats
  that column as confirmed for this fund only. `scripts/refresh_ixbrl_field_status.py` re-reads one
  fund's pages into the artifact (the unified build does not rebuild it).
- **Cause.** The reader already found the column. It did not accept the header label ("Interest"
  to 2025-09-30, "Ref. Rate" from 2025-12-31) or the code "SR +", so every value was marked
  unconfirmed and never applied.
- **Evidence.** 10-Q 2023-03-31: Hg Genesis 9 "E+ | 7.00% PIK". 10-K 2025-12-31: Inovalon second
  lien "S+ | (no cash) | 8.50%" under Ref. Rate, Cash, PIK; Associations Finance "N/A | 14.25%".
  Legend in the 10-Q for 2026-03-31: S = SOFR, E = EURIBOR, C = CORRA, SA = SONIA.
- **Result, sandbox `owlref` (Blue Owl only) against `five16`.** 310 rows gain a reference rate;
  182 of the 247 PIK-only loan rows publish the PIK margin as `basis_spread` (148 SOFR, 12
  EURIBOR, 11 SONIA, 10 LIBOR, 1 PRIME). No other field changes on any of the 8,887 rows.
  Ledger: 63 findings, 0 outstanding.
- **Not covered.** 65 PIK-only rows (3.2B) stay as they were: 37 with an empty cell and 28 with
  "N/A" or an unread code. Most are fixed PIK coupons (Associations Finance 14.25 %); they are not
  published as a coupon. Code "C" is unread (CDOR in 2023, CORRA now), as are "B" and "BB".
- **Found, not fixed.** For rows that already had a reference rate, the published value is an
  inference by date (`inferred_pre_libor`, `inferred_post_libor`), and the fill is blank-only, so
  the inference outranks the printed code. They disagree on 745 of 6,379 rows: 702 in the two
  quarters to 2023-06-30 (printed SOFR, published LIBOR) and 43 later rows (printed EURIBOR, SONIA
  or PRIME, published SOFR; for example Hg Genesis 9 at 2026-03-31).
- **Re-run.** `python scripts/v05_evidence/owl_ref_rate.py owlref five16`.
- **Applies to** Blue Owl only. Five-fund sandbox, semantic diff and any 70-fund build not run.
- **Superseded in part by D-029** (the 65 rows and the unread codes).

### D-029 Blue Owl: both PIK readings, decided per row by the printed column (owner: "do it")

- **Decision.** Three changes, all switched on by Blue Owl's wrapper.
  1. Codes: B and BB = BBSY; C = CDOR to 2024-03-31 and CORRA from 2024-06-30 (a code entry may
     carry `to` or `from` a date; the loader refuses two meanings on one date).
  2. In the filer's named reference-rate column an empty cell or "N/A", on a row that names no
     benchmark anywhere else, is recorded as `not_applicable` in the field-status artifact. The
     overlay then sets a blank `coupon_type` to Fixed on a loan row that carries a rate and has no
     reference rate.
  3. `pik_only_tag_reading: ["coupon", "margin"]`. For a fund with both, a known reference rate
     makes the PIK figure a margin (`basis_spread`); it is the coupon (`interest_rate`, all-in)
     only where the row has no reference rate and `coupon_type` is Fixed. Any other row stays as
     filed. Funds with one reading behave as before.
- **Evidence.** Legends: 10-Q 2024-03-31 "CDOR or C"; 10-Q 2024-06-30 "CORRA or C" for the current
  schedule and "CDOR or C" for the comparative one; 10-Q 2024-09-30 "BBSY or BB"; 10-Q 2026-03-31
  "BBSY or B". Printed rows: Associations Finance "N/A | 14.25%"; Hercules Buyer "0.48% PIK" with
  an empty code cell.
- **Result, sandbox `owlref3` (Blue Owl only) against `five16`.** All 247 PIK-only loan rows are
  resolved: 182 margins (D-028) and 65 fixed coupons (3.2B), from 0.48 % to 14.25 %, eight
  issuers. `coupon_type` changes on those 65 rows only. No other field changes beyond D-028.
  No output column, type or value is new. Ledger: 63 findings, 0 outstanding.
- **Not covered.** A fixed-coupon reading rests on the cell being empty or "N/A" under the right
  header. A row placed under another table's header would be misread; none was seen. A prior-year
  row in a filing takes the current year's printed reading for the same identifier (existing
  behaviour of the artifact). Preferred and common equity rows printed "N/A" are not marked Fixed.
- **Still open (D-028).** The printed code against the date-inferred reference rate now disagrees
  on 780 of 6,414 rows (the new codes add CORRA, CDOR and BBSY rows published as SOFR or LIBOR).
- **Re-run.** `python scripts/v05_evidence/owl_ref_rate.py owlref3 five16`.
- **Applies to** Blue Owl only. Five-fund sandbox, full suite, semantic diff and any 70-fund
  build not run.

### D-030 Three new ledger rules (owner: "add these to the ledger")

- **Decision.** Added to the identity engine (`scripts/shadow_identity_engine.py`), tier tight:
  1. `fourth_quarter_income`: a year-end quarter's total investment income must equal the annual
     figure less the three quarters filed in that year's 10-Qs, within 2 pct. Silent where a year
     lacks three filed quarters. Every fund.
  2. `reference_rate_printed`: the published reference rate must be the code printed in the
     filer's own column. Only funds whose wrapper names that column (Blue Owl).
  3. `spread_printed`: the published spread must equal the total margin printed on the row, to
     the second decimal. Same funds.
- **Not added.** A non-accrual total check for Ares: the fund's stated non-accrual total is not
  extracted, so there is nothing to compare with.
- **Result, five-fund sandbox `five17` (rules 1 and 2 only).** 332 findings, 32 outstanding, all
  from the new rules: `fourth_quarter_income` 19 (BCRED 4, Blue Owl 4, Ares 3, HPS 4, Apollo 4) and
  `reference_rate_printed` 13 (Blue Owl, every quarter). Totals still match in 69 of 69
  fund-quarters. The five funds are therefore not clear.
- **Known cause of each.** Rule 1: the income table stores the annual figure divided by four
  (`pipeline/bdc_fund_income.py`). Rule 2: reference rates inferred from the report date, which
  the printed value does not replace (D-028). Neither is fixed.
- **Applies to** rule 1 every fund: on a 70-fund build it will fire for each fund with a 10-K.

### D-031 Blue Owl: a cash spread printed apart from its PIK margin is published as the total (owner: "go ahead")

- **Finding.** The spread tag changed meaning. To 2024-12-31 Blue Owl prints
  "SR + 6.25% (2.75% PIK)" and tags the total, 6.25. From 2025-03-31 it prints the cash margin and
  the PIK margin in separate cells ("S+ | 2.75% | 2.75%") and tags the cash part, 2.75. Inovalon
  first lien: published spread 6.25, then 2.75, while the printed margin went 6.25, 5.75, 5.50.
- **Decision.** The page reader records `printed_margin` (new column of
  `bdc_ixbrl_field_status.csv`): one figure as is, "A% (B% PIK)" as A, two cells as their sum,
  anything else not read. Wrapper setting `printed_margin_reading: ["cash_plus_pik"]` (Blue Owl):
  on a loan row tagged with a spread and a PIK rate, where the printed margin equals their sum
  and not the spread alone, `basis_spread` becomes the sum, labelled
  `basis_spread:cash_plus_pik_margin`. `pik_rate` is unchanged. The re-verifier replays the sum
  from both facts.
- **Result, sandbox `owlref4` (Blue Owl only) against `owlref3`.** 111 spreads changed, all from
  2025-03-31 on (19, 23, 25, 22 and 22 rows a quarter; 1.2B to 2.3B). No other field changes.
- **What the rule then found.** `spread_printed` compared 6,690 rows; 6 disagree, in 4
  fund-quarters. Kaseya delayed draw and revolver (2023-06-30 to 2023-12-31): printed
  "SR + 6.25% (2.50% PIK)", spread tag 2.5. CivicPlus delayed draw (2024-06-30): printed
  "SR + 5.75% (2.50% PIK)", spread tag 2.5. The filer tagged the PIK part as the spread. Left
  open: a row correction from the printed line is the fix.
- **Blue Owl ledger after this.** 84 findings, 21 outstanding: `reference_rate_printed` 13,
  `fourth_quarter_income` 4, `spread_printed` 4.
- **Not covered.** A printed form the reader does not know is not read and not compared (3 of
  6,693 rows). The published artifact predates the new column and status; it must be re-read
  before a real build uses any of this.
- **Re-run.** `python scripts/v05_evidence/owl_ref_rate.py owlref4 owlref3`.
- **Applies to** Blue Owl only. The five-fund sandbox was not re-run after this change; the other
  four funds do not have the setting.

## 2026-10-07: fixes for the new rules (owner: "keep implementing fixes until there are no outstanding issues left and the data fits the schema")

Five-fund sandbox `five18` after all of these: 299 findings, 0 outstanding; published equals filed
within 0.5M in 69 of 69 fund-quarters; every output file with a contract fits it; the five
wrappers fit the wrapper schema; CSV and Parquet copies match in 9 of 9 artifacts checked.

### D-032 Blue Owl: six spreads corrected from the printed line

- **Decision.** Row corrections for Kaseya (delayed draw and revolver, 2023-06-30 to 2023-12-31,
  spread 6.25) and CivicPlus (delayed draw, 2024-06-30, spread 5.75). The filer tagged the PIK
  part of the margin (2.5) as the spread.
- **Evidence.** 10-Q 2023-06-30: "Kaseya Inc. ... delayed draw term loan SR + 6.25 % ( 2.50 % PIK)
  06/2024 265 225 265". 10-Q 2024-06-30: "CivicPlus, LLC ... delayed draw term loan SR + 5.75 %
  ( 2.50 % PIK) 08/2027 4,590 4,563 4,590". The reader found the same margin in each quarter.
- **Re-run.** `python scripts/v05_evidence/make_row_corrections.py five18` (reports 0 to add).

### D-033 Blue Owl: a printed reference rate replaces one inferred from the report date

- **Decision.** For a fund whose wrapper names its reference-rate column, a confirmed printed
  code replaces a reference rate whose source is `inferred_pre_libor` or `inferred_post_libor`.
  A tagged rate, or one read from the identifier, is never replaced.
- **Result.** 692 rows changed (LIBOR to SOFR in the two quarters to 2023-06-30; SOFR to EURIBOR,
  SONIA, PRIME, CORRA, CDOR or BBSY later). `reference_rate_printed` then holds on every row
  compared.
- **Re-run.** `python scripts/v05_evidence/owl_ref_rate.py five18 five17`.

### D-034 Year-end quarters are the annual figure less the three filed quarters

- **Decision.** `pipeline/fund_financials.py` (`quarter_income_sql`): for income, net investment
  income, total expenses, management fee, incentive fee and interest expense, a twelve-month row
  with three filed quarters in the preceding eleven months becomes annual less those quarters,
  figure by figure. Kept as the average where a quarter is missing, and where three quarters of
  one sign exceed the year figure (the fourth quarter would flip sign). `bdc_fund_income.csv`
  itself is unchanged: it still stores the annual figure divided by four.
- **Result.** All 20 year-end fund-quarters of the five funds change. Total investment income
  was understated by 2 to 50 pct (HPS 2022-12-31: 69.6M published, 139.5M implied by the
  filings; BCRED 2022-12-31: 900.6M against 1,264.8M). `fourth_quarter_income` then holds.
- **Check.** At 2023-12-31 the recomputed gross expenses equal the separately extracted net
  expenses for HPS (127.5M) and Blue Owl (224.4M).
- **Found, not fixed.** Ares interest expense at 2022-12-31 and 2023-12-31 is stored as about
  zero (a year figure of 0.05): the 10-K's figure was not captured. It is left as stored; annual
  less three quarters would have published -314M and -425M. Ares incentive fees are negative in
  several quarters as filed. Other readers of `bdc_fund_income.csv` (`fee_uplift`,
  `rate_convention`, the highlights oracle, the cross-source engine) still see the average.
- **Re-run.** `python scripts/v05_evidence/fourth_quarter.py five18 five17`.
- **Applies to** every fund. Not checked outside the five.

### D-035 Net expenses: no average where the year figure cannot be split

- **Decision.** `pipeline/extract_companyfacts.py`: a figure covering several quarters with no
  earlier year-to-date figure is split using the quarters already known (every field). Where it
  cannot be split, a field marked `quarter_only` gets no value; only `net_expenses` is marked.
- **Cause.** HPS and Blue Owl file net expenses for 2024 in the 10-K only. A quarter of the year
  (164.3M, 300.3M) was compared with the true fourth quarter's income and gross expenses, and the
  income identity failed by 6 to 7 pct.
- **Result.** `net_expenses` is empty for three fund-quarters; the identity then uses gross
  expenses and holds.

### D-036 The wrapper schema admits two fields the code already uses

- **Decision.** `b2_provenance` (written by the B2 wrapper patcher) and
  `invariants.unclassified_rate.max_fv_pct` (read by the content signatures) are declared in
  `wrapper_v3.schema.json`. The build does not validate wrappers against that schema, so the two
  had drifted. A test now holds the five v0.5 wrappers to it.
- **Not covered.** Three wrappers of other funds carry undeclared `notes` fields under `staging`.
- **Re-run.** `python scripts/v05_evidence/schema_fit.py five18`.

### What zero outstanding does not cover (2026-10-07)

- The two page rules run for Blue Owl only. For the other four funds a wrong reference rate or
  spread on the right row is still unseen.
- Ares year-end interest expense for 2022 and 2023 (above); Ares non-accrual loans; Ares SDLP
  principal at 2022-09-30.
- 271 of 299 findings are closed by a recorded disposition, not by a fix.
- Nothing here is in the published data; the published field-status artifact predates the new
  column and status. No quarter outside the development sample has been run.
