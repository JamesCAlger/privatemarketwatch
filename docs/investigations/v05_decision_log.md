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

## 2026-10-07 / 08: printed-page rate checks extended to the other four funds; first out-of-sample quarter

Owner in session: "extend the printed-page rate checks to the other four funds"; "yes, download Q2 2026
for the five funds"; "download companyfacts for Q2 too"; "hold out: yes. timing: run it after five19.
then start fixing". Sandboxes: `five19` (four funds added, no fix), `q2a` (Q2 added, no fix: the
held-out first reading), `q2e` (all fixes below). Code at 6bae284 plus uncommitted changes.

### D-037 The four funds name their reference-rate column

- **Decision.** Wrapper settings, from each fund's printed schedule and legend:
  - BCRED and HPS: column "Reference Rate and Spread" (code cell, then margin cell).
  - Ares: column "Reference" ("SOFR (Q)"), margin in the "Spread" column after it.
  - Apollo: column "Interest Rate", code and margin in one cell ("S+625, 0.50% Floor").
- **Codes from the legends.** BCRED: S = SONIA (the shared table reads S as SOFR), C = CDOR,
  CA = CORRA, ST = STIBOR, CI = CIBOR, N = NIBOR, SA = SARON, B = BKBM, BB = BBSY, F = Fed Funds.
  HPS: SN = SONIA, ST, N, TN = TONA, SORA; C = CDOR to 2025-03-31 and CORRA from 2025-06-30;
  B = BBSW to 2024-09-30 and BBSY from 2024-12-31 (read in all 13 filings). Ares: CDOR, NIBOR,
  BBSY, BKBM, TONA. Apollo: C = CORRA, BBSW.
- **Reader.** `printed_margin` reads three more forms: "A% (incl B% PIK)"; a "Spread" column
  after the reference; basis points after the code in the named cell ("S+325 Cash plus 3.00% PIK"
  is 6.25). A filer's code may carry its reset period ("CDOR (Q)") or lead the cell ("C+525").
- **Not read.** Ares "Base Rate" (the legend says "commonly based on the Federal Funds Rate or the
  Prime Rate": no single benchmark); Apollo fixed coupons in that column; BCRED "Estimated Yield".
- **Result, `five19` against `five18`, no fix.** 343 findings, 44 outstanding, all from the two page
  rules on the four funds. Fair value unchanged on every row.
- **Re-run.** `python scripts/v05_evidence/printed_rate_shapes.py five18 <cik> "<header>"`;
  `python scripts/v05_evidence/printed_rates_check.py five19 five18`.

### D-038 A printed code replaces a reference rate read from the label; a guess is withdrawn where the page prints none

- **Finding.** For BCRED, Ares and HPS nearly every published reference rate was a guess from the
  report date (SOFR from July 2023, LIBOR before), so non-dollar loans were published as SOFR.
- **Decision.** For a fund that names its column: (1) the confirmed printed code replaces a
  reference rate whose source is `identifier_text` as well as `inferred_*`; a tagged rate is never
  replaced. (2) Where the column prints no reference rate, a guessed one is withdrawn and the
  loan's coupon type becomes Fixed. (3) `reference_rate_printed` now also fails a published
  reference rate on a row whose column prints none.
- **Evidence for (1).** BCRED "Prime Security Services Borrower, LLC" and Ares "Prime Buyer,
  L.L.C." were read as PRIME from the borrower's name; pages print SOFR or LIBOR. Apollo 10-Q
  2023-03-31, Garda World: the member reads "L+425", the current-period line prints "S+ 425" (the
  "L+ 425" line is the comparative schedule).
- **Re-run.** `python scripts/v05_evidence/printed_rates_rows.py five19 <cik> reference`.

### D-039 A spread tag on a loan printed with no reference rate is the fixed coupon

- **Finding.** Withdrawing the guesses exposed 33 fund-quarters of X04 ("Fixed coupon row has
  basis_spread"). The filers tag the fixed coupon under the spread concept.
- **Decision.** For a fund that names its column, on a loan row whose column prints no reference
  rate: a spread equal to the filed rate is not published (`basis_spread:fixed_coupon`); where no
  rate is filed the spread figure is published as the rate (`interest_rate:from_spread_tag`) and
  not as a spread, unless the fund's filed rate is read as the cash leg (no v0.5 fund). A spread
  that differs from a filed rate is left alone: tags and page disagree. `provenance_reverify`
  replays both labels from the spread fact.
- **Evidence.** BCRED 10-Q 2022-09-30 "Altice Financing S.A. | 5.75 % | 5.75 %"; 10-Q 2023-03-31
  "AI Altius Bidco, Inc. | 9.75 % | 9.75 % PIK". HPS 10-Q 2025-03-31 "Alliant Holdings Intermediate
  LLC | 6.75 % | 6.75 %"; 10-Q 2024-06-30 "Eagle LNG Partners Jacksonville II LLC | 13.50 % (incl
  6.35 % PIK)". Blue Owl 10-Q 2023-03-31 "Aptive Environmental, LLC | 12.00 % ( 6.00 % PIK)".
- **This is a data choice made without an owner ruling.** It follows X04 and the all-in rate
  convention, and is switched by the wrapper, but it moves a filed figure from one published
  field to another on 109 rows and removes a published spread on 373.

### D-040 Row corrections from the printed line (13 rows)

- Ares 10-Qs 2025-03-31 and 2025-06-30, Clarion (two loans), Equinox, SelectQuote: the spread
  fact holds the coupon and no rate is filed ("12.40 % ( 7.00 % PIK) SOFR (Q) 8.00 %").
- Ares 10-K 2023-12-31, PSC Group loans 2 to 5: rate and spread facts sit one loan down.
- Apollo 10-Q 2024-06-30 Curia ("S+ 38 5", spread fact 0.0038) and 10-Q 2026-03-31 OMH-Healthedge
  (label "S+450", spread fact 0.005).
- **Re-run.** `python scripts/v05_evidence/make_row_corrections.py q2e` (reports 0 to add).

### D-041 One member on two printed rows confirms only what both rows print

- **Finding.** Where two tranches share one member (BCRED 2022-09-30 "Cloudera, Inc." first lien
  L + 3.75 % and second lien L + 6.00 %; HPS 2026-03-31 Sedgwick), the page reader kept the first
  row for both. The second tranche was compared with, and took lien and maturity from, the wrong
  line (HPS Sedgwick second lien was published as First Lien, 2031-07-31; the page prints second
  lien, 2032-07-30). Members that differ only in case are one key ("athenahealth" / "Athenahealth").
- **Decision.** For a fund that names its column, a field of such a member is confirmed only where
  all its rows print the same value; otherwise that field is not read from the page.
- **Cost.** Lien is no longer published on about 20 rows (HPS 10, BCRED 10) and maturity on 86 rows of such members.
- **Not covered.** Funds that name no column keep the old behaviour. Keying the artifact by
  context would read both rows correctly; not built.

### D-042 Apollo: cash plus PIK is published as the total margin

- **Decision.** `printed_margin_reading: ["cash_plus_pik"]` for Apollo (as Blue Owl, D-031).
- **Evidence.** 10-Q 2025-06-30 prints "S + 610 Cash plus 9.77 % PIK"; spread tag 6.1, PIK tag 9.77.
  107 of 109 spread disagreements were this sum.
- **Left open.** Material Holdings then publishes a spread of 15.87 at 2025-06-30 and 2025-09-30,
  outside the range checks (C115, fmt_basis_spread: 4 findings). It is what the page prints.

### D-043 First out-of-sample quarter: 2026-06-30

- **Download.** Five 10-Qs (XBRL and HTML) and five companyfacts files, owner-approved, through
  the rate-limited client; `scripts/download_quarter_filings.py`, `scripts/download_companyfacts.py`.
  The companyfacts files replaced the live cache copies (backups in
  `data/raw/filings/quarter_downloads/companyfacts_2026-06-30/before`). The published filings index
  is unchanged; `scripts/sandbox_add_quarter.py` adds the quarter to a sandbox only.
- **First reading, `q2a`, nothing fixed.** Published equals filed investments to 0.0M for all five
  funds (Apollo's two money-market funds, 407.9M, are printed after "Total Investments before Cash
  Equivalents" and classed as cash). 27 findings at the quarter: 6 cleared by standing
  dispositions, 21 open. Rows and fair value of every earlier quarter identical to `five19`.
- **What did not carry.** (1) Dispositions and row corrections tied to listed quarters: 15 of the
  21. (2) Ares changed its member format (D-044). (3) Three row-level items read on the Q2 page and
  corrected: Blue Owl Amergin (class), HPS OneTeam (preferred), Blue Owl KWOR (cost fact in EUR).
- **Re-run.** `python scripts/v05_evidence/new_quarter_reading.py q2a five19 2026-06-30`.

### D-044 Ares: the member is "Issuer | Instrument" from 2026-06-30

- **Finding.** 1,431 of 1,439 Ares members at 2026-06-30 use a pipe; before, a comma. The wrapper
  cut the name at the last comma, so "Kellermeyer Bergensons Services, LLC and KBS TopCo, LLC |
  Class A common units" became issuer "...KBS TopCo". Totals and classes were unaffected; only
  27.3 pct of issuers matched the quarter before. Rule D06 caught it.
- **Decision.** The Ares wrapper's issuer and instrument patterns accept both forms.
- **Result.** 93.6 pct continuity at 2026-06-30; 0 of 18,341 earlier rows change issuer or instrument.
- **Re-run.** `python scripts/v05_evidence/ares_member_format.py q2e five19`.

### State after `q2e`

331 findings, 27 outstanding (12 before 2026-06-30, 15 at it). Published equals filed in 74 of 74
fund-quarters. Outputs and the five wrappers fit their schemas (`schema_fit.py q2e`).
Changes to rows up to 2026-03-31 against `five18` (`printed_rates_effect.py q2e five18`):

| Change | BCRED | Blue Owl | Ares | HPS | Apollo |
|---|---|---|---|---|---|
| Date-guessed reference rate replaced by the printed code | 2,280 | 0 | 1,719 | 1,138 | 74 |
| Label-read reference rate replaced by the printed code | 13 | 0 | 7 | 0 | 22 |
| Guessed reference rate withdrawn | 275 | 41 | 1 | 63 | 0 |
| Fixed coupon no longer published as a spread | 275 | 40 | 0 | 58 | 0 |
| Rate published from that spread tag | 64 | 40 | 0 | 5 | 0 |
| Cash plus PIK published as the total margin | 0 | 0 | 0 | 0 | 107 |
| Fair value changed | 0 | 0 | 0 | 0 | 0 |

**Open, for the owner**

1. **BCRED loses lien position on 3,304 rows (2022-09-30 to 2024-06-30) when its pages are
   re-read.** Not caused by these changes; exposed by them, since they need the re-read. The lien
   gate in `extract_bdc_ixbrl_field_status` takes only `lien_only` rows of `bdc_lien_breakdown.csv`
   whenever any exist in the file. For BCRED those quarters hold one such row (Unsecured, about
   36M, and twice, under cik `1803498` and `0001803498`), the page has no matching tier, and the
   whole filing's lien is withheld. From 2024-09-30 BCRED has no `lien_only` row and passes with
   no check at all. A gate on the complete grain would fail too: the page sum includes the JV
   schedules (First Lien 51.0B on the page, 45.1B filed at 2023-12-31). No rule flags the loss.
   `python scripts/v05_evidence/lien_gate.py q2e 0001803498`. Ares also loses lien on 7 rows on the
   re-read; cause not traced. **Fix before any promotion.**
2. **15 findings at 2026-06-30** (X02 and X06 for Ares, BCRED, Blue Owl, HPS; C107 for Apollo and
   HPS; HPS C103 and X07 Thrasio; Blue Owl SRC_BDC01, source reconciliation and FX03). The earlier
   quarters' evidence scripts give the same picture on Q2 (negative cost filed on every row; deep
   markdowns, the same borrowers in Ares and BCRED; unfunded-commitment rows). Proposed: the same
   dispositions. Not accepted by me: last session's permission was for that run.
3. **Blue Owl Aptive, 7 quarters:** a rate of 12.0 with a PIK rate of 6.0 is now published and the
   fund declares no filed-rate reading, so `financial_convention_unresolved` fires. The page
   prints "12.00 % ( 6.00 % PIK)": all-in. `rate_convention.csv` records Blue Owl as cash leg.
4. **Apollo Material Holdings spread 15.87** (D-042): 4 range findings; as printed.
5. **Ares UP Intermediate revolver, 2025-09-30:** rate 8.75 and spread 4.75 are tagged on a line
   the page prints with no rate (they are the term loan's). One finding; fair value 0.0M.
6. **D-039** is a data choice applied without a ruling.
7. **Ares "Base Rate" loans** (about 250 rows in five filings sampled) keep a guessed SOFR.

**What this does not show.** The page rules compare a row only where the reader confirmed the
cell; unread rows are not compared. A row keyed to the wrong printed line by a shared member is
excluded, not checked. One out-of-sample quarter is one observation.

## 2026-10-08 (later): two rule defects, Blue Owl equity labels, dispositions that carry forward

Owner in session: "yes, start on step 1 and 2" (step 1: fix the two rule defects and the
misclassified Blue Owl rows; step 2: make dispositions carry forward with a validity check).
Sandbox `q2f` (inputs of `q2e`, rebuilt from the holdings stage). Uncommitted.

### D-045 Two rules fired on rows that are not their subject

- **X02** (credit row with no rate and no spread) fired on stakes in credit vehicles, which carry
  no coupon. At 2026-06-30: Ares Ivy Hill member interest 1,897M, Blue Owl OCIC SLF 261M, BCRED
  Muzinich LP interest 29M. **Decision:** the rule skips rows with asset category FUND or index
  class PRIVATE_CREDIT_FUND. Shared rule, all funds; it narrows a check and changes no data.
- **SRC_BDC01** (source row with no published position) fired on every blocking row of the
  reconciliation detail, including rows the reconciliation's own second pass documents as totals,
  headers or wrapper-named rollups ("Total non-controlled/affiliated - debt commitments").
  **Decision:** the rule skips a source row that pass marks non-blocking. A row it does not list
  fires as before.
- **Result.** BCRED X02 gone at 2025-12-31 and 2026-03-31 and not raised at 2026-06-30; SRC_BDC01
  gone at Blue Owl 2025-06-30 and Apollo 2024-03-31, 2024-06-30, 2025-03-31.
- **Tests.** `tests/test_column_validation.py` (one false-positive and one still-fires case each).

### D-046 Blue Owl: equity printed under labels no keyword knows

- **Finding.** X02 flagged "Blue Owl Credit SLF LLC | LLC interest" (90.6M), "Blue Owl Leasing LLC |
  LLC Interest" (1.9M) and "Valor CI Blocker Feeder LP | Investment partnership" (10.3M) as loans
  with no rate. The 10-Q for 2026-06-30 prints Valor in the equity section ("Investment partnership
  N/A N/A 9,912 - 9,640 10,345"). The filer tags the unit count as a principal, and the field
  heuristic reads a principal as a loan. A blanket "as filed" disposition of X02 would have
  buried all three.
- **Decision.** New wrapper setting `equity_instrument_labels` (exact instrument description,
  consulted after every keyword and before the field heuristic), set for Blue Owl to "LLC
  interest" and "Investment partnership". A shared keyword was rejected: on the published
  holdings it would touch about 170 loan or unclassified rows in 20 funds, some of them real
  loans ("... LLC Interest Rate ...").
- **Side effect found and fixed.** The first run dropped the Valor row (Blue Owl 10.3M below its
  filed total at 2026-06-30). An equity row publishes no principal, so the row reached the fund's
  roll-forward exclusion rule with no quantity and no instrument phrase the rule knew. The rule's
  phrase list now includes "investment partnership". The carry-forward check of D-047 caught the
  drop (published differs from filed by -10.3M).
- **KWOR cost.** The correction of D-043 set the cost, but the cost's unit stayed EUR and a cost
  whose unit is not the dollar is withheld. Row corrections may now set `cost_currency`; one row
  added. Cost 6,675,000 is published and FX03 no longer fires.
- **Result against `q2e`** (`python scripts/v05_evidence/holdings_field_diff.py q2f q2e`): 5 Blue
  Owl rows move from loan to common equity (and lose the "principal" that was a unit count); 1
  cost; 1 new row at zero value (Valor's unfunded commitment line); 89 of 99 columns identical on
  every row. Published equals filed in 74 of 74 fund-quarters.
- **Left open.** The unit count of those rows is not published (it is tagged as a principal).
  Blue Owl's share of equity rows with units at 2026-06-30 falls from 73.5 to 69.4 pct, under the
  oracle's 70 pct line, so C04 now fires there.

### D-047 A disposition reaches a new quarter only through a check that passes

- **Problem.** 15 of the 21 open findings at 2026-06-30 were patterns accepted for earlier
  quarters. Entries list their quarters, so none carried; the alternative on offer was accepting
  them again by hand each quarter.
- **Decision.** An entry may carry `carry_forward: {from, check, params}`. It covers a quarter on
  or after `from` only when the named check passed on that fund-quarter's own outputs
  (`pipeline/disposition_validity.py`; the sandbox runs it before the ledger). No recorded pass,
  no cover. The ledger marks each closure `listed` or `carried_forward`. `make_dispositions.py`
  no longer lists a quarter after 2026-03-31.
- **Checks.** `values_as_filed` (C107 cost, C103 fair value, X06 principal and fair value): every
  flagged row publishes the field as the filed fact, per the provenance re-verifier.
  `no_rate_in_source` (X02): every flagged row has no rate or spread fact and is undrawn (value
  at or below zero), on non-accrual, or publishes a PIK rate. `missing_source_rows_known` (Blue
  Owl SRC_BDC01 and source reconciliation): every blocking source row matches a named pattern and
  published equals filed within 0.5M. The two Blue Owl patterns are the footnote on BOCSO's own
  portfolio ("five investments totaling $1.25 billion and $1.24 billion at cost and fair value
  ... ranging ... from $24.9 million to $450.6 million") and the issuer lines of the
  controlled-affiliates table ("Notorious Topco ... 126,405", the sum of its four published
  positions). DS-016 called these "issuer-level or subtotal rows"; for BOCSO that was loose.
- **Result at 2026-06-30** (`q2f`): 10 findings closed by a passing check (C107 Apollo and HPS; X06
  Ares, BCRED, Blue Owl, HPS; C103 HPS; X02 Blue Owl; Blue Owl SRC_BDC01 and source
  reconciliation). Two checks failed and their findings stay open: HPS X02 (7 funded rows, 2.0M,
  no rate fact) and Ares X02 ("Axiomatic, LLC | First lien senior secured notes", 0.1M).
- **The same checks on the quarters already accepted** (not reopened; a measure of the old
  entries): `values_as_filed` passes 77 of 77 fund-quarters. `no_rate_in_source` passes 10 of 46:
  HPS 0 of 14 (184 rows, 40.7M), Ares 3 of 16 (33 rows, 643.9M), Blue Owl 7 of 14 (8 rows,
  66.8M), Apollo 0 of 2 (2 rows, 95.5M, the Spirit Aerosystems loan DS-006B documents). So the
  X02 "as filed" entries cover rows their stated reason does not explain. They need a row-level
  reading against the printed page; another session found two wrong ones at Ares.
- **Limits.** `values_as_filed` proves the published figure is the filed one, not that the filed
  one is sensible; it will keep closing C107, C103 and X06 for these funds until a flagged value
  stops being a filed fact. The X02 check does not read the printed page. A check that passes
  closes the finding without a person looking; the owner approved the mechanism, not each
  closure.
- **Tests.** `tests/test_disposition_validity.py` (8), `tests/test_finding_dispositions.py`.

### State after `q2f`

325 findings, 17 outstanding (12 before 2026-06-30, 5 at it). Published equals filed in 74 of 74
fund-quarters. Wrappers fit the schema.

At 2026-06-30:

| Finding | What it is | Proposed |
|---|---|---|
| HPS X07 | Thrasio LLC loan, value 300 against cost 8 (thousands) | As filed: the page prints "SF + 8.00 % 12.01 % 6/18/2029 300 8 300" and the industry cost total 24,258 is 24,250 + 8. Needs the owner's acceptance. |
| HPS X02 | 7 funded rows with no rate fact (2.0M) | Read on the page |
| Ares X02 | Axiomatic first lien notes, 0.1M, no rate fact | Read on the page |
| Apollo B01 | 99 of 1,649 position contexts with no fair value fact | Same pattern as DS-010; no check written for it |
| Blue Owl C04 | 69.4 pct of equity rows carry units (line is 70) | Publish the unit count tagged as principal (D-046) |

**The first reading of 2026-06-30 was short by at least one finding.** In `q2a` to `q2e` the
oracle did not evaluate its per-quarter checks for Apollo at 2026-06-30 (58 lines of the oracle
log name the quarter, against 77 in `q2f`, which re-ran the same inputs from the holdings stage).
Apollo B01 at 2026-06-30 fails in `q2f` and was absent before. Cause not traced: the oracle seems
to take its quarters from an output of an earlier pass. A first pass on a new quarter may
under-report until this is understood.

Open items 1 and 3 to 7 of the previous entry stand unchanged (BCRED lien, Blue Owl Aptive,
Apollo Material, Ares UP Intermediate, D-039, Ares "Base Rate").

## 2026-10-08 (evening): the oracle's stale input, Thrasio, and the old X02 rows read on the page

Owner in session: "yes to all three" (accept Thrasio as filed; read the old X02 rows against the
printed pages, HPS and Ares first; trace the oracle under-reporting before other Q2 work).
Sandbox `q2g` (inputs of `q2f`, rebuilt from the holdings stage). Uncommitted.

### D-048 The oracle read the previous build's reconciliation

- **Finding.** Oracle checks A01, B01, B07 and E07 read `source_reconciliation_detail.csv`. The
  validate stage writes that file, and both the sandbox and `scripts/run_quarter_pass.py` run the
  oracle before validate. So those four checks always described the previous build, and on the
  first pass with a new quarter they skipped it: in `q2a` to `q2e`, 58 oracle lines name
  2026-06-30; with the file in place, 77. The 19 missing lines were A01 for four funds and B01,
  B07 and E07 for all five.
- **Decision.** The sandbox runs the oracle after validate. `pipeline/oracle_runner.py` logs
  "STALE INPUT" when the detail file is older than the holdings.
- **Not changed.** The quarter pass has the same order (`rebuild -> oracle -> nonaccrual ->
  validate`, and again in the post round). Every oracle result of those four checks in a past
  quarter pass describes the build before the one it was reported for. Reordering the pass is the
  owner's call; the warning now shows in its oracle log.
- **Result.** `q2g`: 77 lines for 2026-06-30, no stale warning. One finding the first reading
  missed: Apollo B01 (99 of 1,649 position contexts with no fair value fact).

### D-049 Old "as filed" X02 entries, read on the printed page

`python scripts/v05_evidence/x02_page_read.py q2f <cik>` prints, for each X02 row the entry's
reason does not explain, the printed line found by issuer and value.

- **Ares, 33 rows in 13 quarters (643.9M), accepted under DS-006A.**

  | What the page shows | Rows | Fair value | Done |
  |---|---|---|---|
  | No rate printed (marked-down loans; the data carries no non-accrual flag for them) | 17 | 236M | As printed. Stay under DS-006A. |
  | A rate is printed and none was published | 9 | 288M | 4 corrected; 4 cannot be (below); Centric Brands 2022-09-30 ("11.80 % PIK SOFR (Q) 9.00 %", 71.2M) not yet corrected |
  | The value is an equity line; the filer's member names a loan | 5 | 113M | Corrected to the printed instrument and class |
  | Not found by name and value | 2 | 7M | Murchison 6.7M (cost 0), Viant 0.5M |

  Counts by my reading of 33 printed lines; the fair values are sums of the rows as published.
- **Rates corrected (4 rows):** HPCC Parent 2024-12-31 (13.00, PIK 7.00); Sunrun Xanadu
  2022-09-30 (10.43, PIK 2.77, spread 6.75); The Hiller Companies 2025-09-30 (9.05, spread 4.75);
  Imaging Business Machines 2025-09-30 (14.00, PIK 7.00: the published PIK rate was 14.0, the
  whole coupon).
- **Not correctable by a row correction (4 rows, 51.6M):** Rawlings loan 2 and Infinity Home
  Services loan 3 at 2025-03-31 and 2025-06-30 print a rate but are among the eight positions
  restored from the issuer-name axis (D-018), built after row corrections apply. The fix belongs
  in that restoration.
- **Equity under a loan member (5 rows):** in the 10-Qs for 2025-09-30, 2025-12-31 and 2026-03-31
  a member reading "... First lien senior secured loan" carries the units, cost and value of an
  equity line of the same issuer (Implus Footcare common units 42.1M; Bragg Live Food common
  units 22.3M; ID.me Series E preferred 16.0M; Ardonagh LP interest 26.3M; APG class A units
  6.3M). The numbers were right; the instrument and class were not. Corrected by row.
  A published loan with a unit count, no principal and no rate is the signature; Ares has no
  other such row above 0.1M outside 2023-06-30 (two rows there carry a rate and were not read).
- **HPS, 184 rows (40.8M), accepted under DS-006.** The 45 largest read on the page: undrawn
  lines printed with par, a negative cost, a small positive value and no rate ("7/22/2031 43,333
  ( 202 ) 433"), plus rows of the joint-venture schedule, which are not published. **Decision:**
  the X02 check counts a negative cost as undrawn. HPS then passes at 2026-06-30 and in 6 of 14
  quarters; the 24 rows left (17.8M) are JV-schedule rows with no cost fact, and three funded
  positions printed with no rate (SLF V AD1 8.1M, Southern Graphics 2.3M twice).
- **Blue Owl and Apollo** (8 and 2 rows): not read in this pass. Blue Owl's are the Aptive rows
  of the open rate-reading question and one KOBHG "Class A Interests" row; Apollo's is the Spirit
  Aerosystems loan DS-006B documents.
- **What this says about the old entries.** For Ares, 14 of 33 rows accepted "as filed" were not:
  the page had a rate, or the row was equity. They were closed without a row-level read.

### D-050 Thrasio LLC, HPS 2026-06-30: as filed (owner)

X07 flags a loan worth more than ten times its cost. The page prints "Thrasio LLC ... SF + 8.00 %
12.01 % 6/18/2029 300 8 300" and the industry cost total 24,258 is 24,250 plus 8. Owner accepted
in session. Entry DS-029, listed for 2026-06-30 only, no carry-forward.

### State after `q2g`

325 findings, 15 outstanding (12 before 2026-06-30, 3 at it). Published equals filed in 74 of 74
fund-quarters. Against `q2f` (`holdings_field_diff.py q2g q2f`): 9 Ares rows change (5 class and
instrument, 4 rate); no other fund, no row added or lost.

At 2026-06-30: Ares X02 (Axiomatic notes, 0.1M, printed with no rate; needs acceptance), Apollo
B01 (same pattern as DS-010; no check written), Blue Owl C04 (D-046).

Before 2026-06-30, unchanged: Blue Owl Aptive 7, Apollo Material Holdings 4, Ares UP Intermediate 1.
Open items of the earlier entries stand (BCRED lien loss first).

## 2026-10-08 (night): the lien reader and its gate; the quarter pass order

Owner in session: "do all 3" (reorder the quarter pass; fix the BCRED lien loss; commit).
Sandbox `q2h` (inputs of `q2g`, pages re-read, rebuilt from the holdings stage).

### D-051 BCRED lien: three defects in the page reader and its gate

The open item was "re-reading BCRED's pages withholds lien on 3,304 rows". The cause was wider.

- **The gate's reference was wrong.** It read `bdc_lien_breakdown.csv`, chose one grain for the
  whole file, and summed a fund's rows under both spellings of its CIK. For BCRED that left one
  stray tier (Unsecured, about 36M, counted twice) as the fund's whole breakdown; for Apollo and
  HPS it left nothing, so they passed with no check. The fuller grain is not a good reference
  either: at 2025-09-30 it holds Second Lien 2,216M where the page prints "Total Second Lien Debt
  ... 3,129,503".
- **The reader mislabelled rows.** It knew a fixed list of section headings. BCRED's "Structured
  Finance Obligations" and "Equity and other" were not on it, so their rows kept the last lien
  heading: at 2025-09-30, 263 rows read as Unsecured (first of them a CLO tranche) against a
  printed Unsecured total of 87.5M, and equity units read as Second Lien. Headings with an
  affiliation suffix ("First Lien Debt - controlled/affiliated") and the 10-Q for 2025-03-31
  ("First Lien", "Second Lien") were not recognised either. Outside a section the reader fell
  back to words in the row ("Subordinated Notes" of a CLO).
- **One tier withheld every tier.** HPS 2025-09-30: First Lien 24,152M on the page rows against
  a printed 24,171M, withheld with the rest because one 25M second-lien position was not read.
- **Decision.**
  1. A lien section ends at its own total row ("Total Second Lien Debt"); a heading the reader
     does not know can no longer inherit it. Two headings added; "Debt" optional; an affiliation
     suffix is part of the heading. In a schedule laid out in lien sections, the row's words are
     not a lien tier.
  2. The gate's reference is the page's own section totals (the tagged fair value on the total
     row, in the current period), where the page prints them. The filed breakdown is the
     fallback: distinct rows, and per fund-quarter the grain with the most fair value.
  3. The withhold is per tier.
  All in the shared reader. It changes published data only where a fund's page artifact is
  re-read; measured on the five funds only.
- **Result, BCRED** (`python scripts/v05_evidence/lien_gate.py q2h 0001803498 <quarter>`): the
  page rows tie to the page totals in 14 of 16 quarters, to the dollar in the ones checked by hand
  (2024-03-31 First Lien 52,802.2M, Second Lien 1,552.0M, Unsecured 26.4M; 2025-03-31 68,798.3M,
  3,037.3M, 126.9M). Against `q2g`: 4,581 rows gain a tier (4,357 First Lien), 528 change tier
  (520 Second Lien to First Lien), 205 lose a wrong one (146 Unsecured, 59 Second Lien). Loans
  without a tier are 5 to 9 pct of BCRED's loans in those 14 quarters.
- **Still withheld: BCRED 2022-09-30 and 2022-12-31** (992 of 1,034 and 1,276 of 1,277 loans
  without a tier). Those filings use one member for several printed rows, so the rows read cover
  37.6B of a printed 49.7B First Lien at 2022-12-31. The gate is right to fail; the reader cannot
  tie a row to its tier there.
- **HPS:** 30 rows change (16 Second Lien to Unsecured, 9 gain Unsecured, 5 lose Second Lien).
  **Ares:** 1 row. Blue Owl and Apollo: none. No other column changes on any row
  (`holdings_field_diff.py q2h q2g`: 97 of 99 columns identical; 6 position ids move).
- **Not done.** No rule reports a lost or changed lien tier; this was found by comparing fields
  between sandboxes. The 2022 filings need a row-level key. The other 65 funds were not re-read.
- **Tests.** `tests/test_bdc_xbrl_html_bridge_fields.py` (five new).

### D-052 The quarter pass runs the oracle after validate (owner)

`scripts/run_quarter_pass.py`: `rebuild -> nonaccrual -> validate -> oracle -> ...` in both rounds
(D-048 gives the reason). Results of oracle checks A01, B01, B07 and E07 in passes before this
date describe the build before the one they were reported for. AGENTS.md still lists the old
order in two places; it is the owner's file.

### State after `q2h`

325 findings, 15 outstanding (12 before 2026-06-30, 3 at it), unchanged from `q2g`. Published
equals filed in 74 of 74 fund-quarters.

## 2026-10-08 (late night): owner rulings on the open items; final validation of the five funds

Owner in session: "yes to 1, 2, 3, 4, 7. do 5, 6 and 8", then "do a final validation of the 5 funds,
then prepare the next 5 by size for the same exercise, for data to Q2 2026".
Sandbox `final5`: the whole chain from an empty sandbox, then one re-run from the holdings stage.

### D-053 Owner rulings recorded

| Ruling | What was done |
|---|---|
| Ares Axiomatic notes at 2026-06-30: as filed | DS-030, that quarter only |
| Apollo Material Holdings spread 15.87: as printed | DS-031 (C115), DS-032 (fmt_basis_spread), 2025-06-30 and 2025-09-30 |
| Apollo B01 at 2026-06-30: as earlier quarters | 2026-06-30 added to DS-010 |
| Fixed coupon tagged as a spread (D-039): keep | Ratified; no change |
| Ares UP Intermediate revolver: follow the page | Three rows corrected (below) |
| Blue Owl Aptive: correct the seven rows | Rate 12.0 published, PIK 6.0 unchanged |

- **Aptive.** All seven 10-Qs and 10-Ks from 2023-03-31 to 2024-09-30 print "First lien senior
  secured loan 12.00 % ( 6.00 % PIK) 01/2026" (each read; the row's printed value matches the
  published one). Blue Owl still declares no fund-wide rate reading.
- **UP Intermediate, Ares 10-Q 2025-09-30.** The members are one line out, as in D-049. The page
  prints the revolver with no rate, "First lien senior secured loan 8.75 % SOFR (Q) 4.75 % ...
  15.2 15.2 15.2" and "Senior preferred units 15.00 % PIK". Published before: revolver 8.75 and
  4.75, term loan 15.0 PIK, preferred units nothing. Corrected on all three rows; the ruling
  named the revolver only. Row corrections may now set `reference_rate_type`,
  `reference_rate_source` and `coupon_type`, and an empty value is stored as a missing value.

### D-054 Ares "Base Rate": the guessed benchmark is withdrawn (owner)

- **Decision.** New wrapper setting `unspecified_reference_labels`, set for Ares to "Base Rate".
  The reader gives such a cell the status `unspecified`; the overlay then withdraws a reference
  rate that was guessed from the report date or read from the identifier text, and changes
  nothing else on the row (the loan floats; its rate and spread stand).
- **Result.** 380 Ares rows lose a reference rate, 20 to 35 a quarter. One was not a date guess:
  "Prime Buyer, L.L.C." at 2022-09-30 published PRIME, read from the borrower's name; the page
  rule caught it on the first run.
- **Tests.** `tests/test_bdc_xbrl_html_bridge_fields.py`, `tests/test_source_encodings.py`.

### D-055 Blue Owl: the unit count tagged as a principal is published as units (owner)

- **Decision.** For a row classed equity through `equity_instrument_labels` with no unit fact and
  a principal fact, the principal is published as `shares_held` (transform
  `shares_held:from_principal_tag`; the re-verifier anchors it on the principal fact).
- **Result.** Seven Blue Owl rows (Credit SLF, Leasing, Valor CI). Equity rows with units at
  2026-06-30: 73.6 pct (was 69.4); C04 passes.
- **Not clean.** At 2025-12-31 the two rows already carried a derived unit count. They now show
  the tagged figure but keep the label of the unit-normalisation step (`derived_proxy`,
  `pow10_shares`), and Blue Owl Leasing shows 1,900,000 units against a value of 17.2M there and
  1.9M a quarter later. Not checked against the page.

### Final validation, `final5`

| Check | Result |
|---|---|
| Findings, five funds, 2022 to 2026-06-30 | 316; 0 outstanding |
| Published against filed investments | within 0.5M in 74 of 74 fund-quarters (worst: Ares 0.5M) |
| Row ids | 71,434 rows, 71,434 distinct, none empty |
| Provenance re-check | no failing state; 9 `anchor_missing` (dispositioned, DS-019) |
| Outputs and wrappers against their schemas | fit |
| Oracle coverage of 2026-06-30 | 77 lines (all five funds, all per-quarter checks) |
| Against `q2h`, field by field | only the rows of D-053 to D-055 differ; no row added or lost |

How the 316 are closed is in `scratch/fund_sandbox/final5/findings_ledger.csv` (`state`,
`disposition_basis`).

**What the clean build caught that the incremental ones had not.**
- The first full run stopped in the rebuild: an empty correction value was written as empty text
  and a later numeric cast failed. Fixed (missing value), with a test.
- Two findings appeared and were fixed: the Prime Buyer reference rate (D-054) and a coupon type
  left "Floating" on the revolver whose rate was withdrawn.

**What "0 outstanding" does not say.** Of the 316 findings, 288 are closed by a disposition (173
"as filed", 79 informational, 36 not applicable), 27 by an earlier reviewer's
false-alarm verdict and 1 by a promoted fix. Eleven of the dispositions, all at 2026-06-30, are
carried forward by a check with nobody looking. The X02 "as filed" entries for earlier
quarters still cover rows their reason does not explain (D-047, D-049). BCRED has no lien tier
for 2022-09-30 and 2022-12-31. Five Ares rows print a rate that is not published. No rule
detects a wrong value on the right row. Nothing here has been checked on the other 65 funds.

### D-056 The next five funds: data to 2026-06-30 and an untouched first reading

- **Which five.** The next five of the 70-fund cohort by published fair value at 2026-03-31 (the
  basis the first five were chosen on; published build of 2026-10-01): Ares Strategic Income Fund
  (0001918712, 21.3B), Goldman Sachs Private Credit Corp. (0001920145, 17.1B), Golub Capital
  Private Credit Fund (0001930087, 9.8B), Sixth Street Lending Partners (0001925309, 8.6B),
  Oaktree Strategic Credit Fund (0001872371, 7.0B). By size over all filers the list would
  differ: FS KKR Capital, Blue Owl Capital Corp and Blue Owl Technology Finance are larger but
  are not in the cohort and have no wrapper.
- **Downloads (network, on the owner's request for data to Q2 2026).** Five 10-Qs for 2026-06-30
  and five companyfacts files, through the rate-limited client. The companyfacts files replaced
  the live cache copies (backups in `data/raw/filings/quarter_downloads/companyfacts_2026-06-30/before`).
  `download_quarter_filings.py` replaced the quarter's index with the new five on this second
  run; the index was restored to ten funds from a copy before any build read it, and the script
  now merges.
- **Not changed.** `findings_scope.ciks` still names the first five: widening the sign-off scope
  is the owner's decision. Nothing was fixed for these funds.
- **First reading, sandbox `next5a`, 2022 to 2026-06-30.** 501 findings, 409 outstanding (Sixth
  Street 119, Goldman Sachs 107, Oaktree 74, Golub 63, Ares Strategic Income 46); 41 of them at
  2026-06-30. Published equals filed investments within 0.5M in 49 of 67 fund-quarters (Oaktree
  13 of 14, Ares Strategic Income 12 of 14, Sixth Street 9 of 14, Golub 8 of 12, Goldman Sachs 7
  of 13; worst gap 201.7M at Goldman Sachs, the one fund-quarter more than 1 pct out). At
  2026-06-30 the gaps are 13M, 23M, 6M, 0M and 71M of 6.8B to 21.8B.
- **Largest groups of outstanding findings.** No declared rate reading (65), credit rows with no
  rate (X02, 47), principal with no dollar equivalent (FX01, 41), negative cost (C107, 29),
  principal far above value (X06, 20), percent of net assets (20), negative value (C103, 17).
  Several are the patterns the first five funds needed a wrapper setting or a disposition for.
- **State of their configuration.** All five have a v3 wrapper; none has `source_encodings`
  (no named reference-rate column, no rate reading), and none has a fund-highlights wrapper. The
  page checks added for the first five do not run for them until a wrapper names the column.
- **Re-run.** `bash scratch/2026-10-07_printed_rates/run_next5a.sh`;
  `python scripts/v05_evidence/matrix.py next5a`.

## 2026-10-08 (night, 2): next five funds, first two (Oaktree, Ares Strategic Income)

Owner in session: "yes to 1 and 2. widen scope after" (commit; start fixing the next five; the
sign-off scope stays at five funds until the next five are clean). Sandbox `n2a` (these two funds,
2022 to 2026-06-30). Uncommitted.

### D-057 Ares Strategic Income (0001918712): the Ares Capital wrapper settings, each checked on its page

- **Issuer and instrument were not split before 2026-06-30.** The wrapper had no label patterns,
  so the issuer was the whole label ("1261229 B.C. LTD., First lien senior secured loan"): 1,222
  issuers for 1,223 rows at 2025-12-31. With the patterns, 867. The published build has the same
  defect for this fund.
- **Nine CLO tranches were dropped at 2026-06-30 (22.7M, the whole gap to the filed total).** From
  that filing two tranches of one CLO are told apart by a third segment holding the coupon
  ("SIXST 2022-21 | Collaterized loan obligation | 9.42%"). A shared rule reads a label ending in
  a percentage as a subtotal unless the name looks like a company or the wrapper classes it as a
  position; then the fund's label condition refused a last segment with no instrument word.
  The wrapper now classes instruments (the filer spells it "Collaterized"), and its label
  patterns and condition accept the coupon segment.
- **Rate settings** (page: "Coupon | Reference | Spread"; "9.94 % ( 3.13 % PIK) SOFR (Q) 6.25 %",
  published rate 9.94; "11.37 % PIK SOFR (Q) 7.50 %"; "Base Rate (Q)" 15 times in the 10-K for
  2025-12-31): `filed_rate_reading` all_in, `pik_only_tag_reading` coupon,
  `reference_rate_columns` Reference, `unspecified_reference_labels` Base Rate.
- **Result.** 46 outstanding to 23. Published equals filed within 0.5M in 13 of 14 quarters.
- **Open.** 2025-03-31 is 28.7M short (13,626.4M against a printed 13,655.1M): the filing's
  tagged position rows themselves sum to 13,626.1M, so about 29M of positions carry no position
  tag. Not traced to rows. X02 (10 findings) and X06 (5) not yet read on the page.

### D-058 Oaktree Strategic Credit (0001872371)

- **Rate settings** (page: "Index | Spread | Cash Interest Rate | PIK"; Legends Hospitality cash
  6.41, PIK 2.75, spread 5.50): `filed_rate_reading` cash_leg, `reference_rate_columns` Index,
  `principal_usd_reference` fred_h10 (39 to 44 rows a quarter had a foreign principal and no
  dollar equivalent).
- **Joint-venture stake counted twice at 2026-06-30 (13.15M, the whole gap).** The schedule row
  (context c-53: shares 0.250, cost 13,104, fair value 13,148) and a second row from the
  joint-venture note (c-2092: ownership percentage, fair value, percent of net assets; no cost or
  share fact) were both published. New promoted rule
  `agent_investigate_rules/1872371/exclude_edl_jv_note_row.json`: structural, every quarter, one
  issuer. One quarter of evidence (the venture was formed in May 2026).
- **Result.** 74 outstanding to 42. Published equals filed within 0.5M in 14 of 14 quarters.
- **Open, mostly for dispositions.** C107 negative cost (10 quarters), X02 (9), X06 (5), F28 (4):
  the patterns the first five funds closed by disposition; not proposed yet. At 2026-06-30 two
  euro-tagged fair values are converted (882,000 to 1,006,979); the total ties with the
  converted figures, so the reconciliation's mismatch on them is a rule artefact.

## 2026-10-08 (night, 3): next five funds, the other three (Golub, Sixth Street, Goldman Sachs)

Owner in session: "commit, then do the next three in any way you deem fit". Sandbox `n3a` (these
three funds, 2022 to 2026-06-30). Uncommitted.

### D-059 Goldman Sachs Private Credit (0001920145)

- **A promoted rule had invented 349.4M of fair value at 2026-03-31; pulled.**
  `restore_2026q1_principal_only_debt_positions` added Auctane, Inc. (193.0M) and Tiger
  Acquisition, LLC (156.4M) with the principal as the fair value. The 10-Q prints both with a par
  and no cost or value ("Auctane, Inc. ... S + 4.75 % 12/31/32 193,000 - -"): undrawn commitments.
  The gap the rule closed was measured against "Total Investments and Investments in Affiliated
  Money Market Fund ... 16,852,129"; the filed total of investments is 16,508,590. The gap was the
  money-market fund (343.5M) plus one 5.8M row. Moved to
  `agent_investigate_rules/_pulled_fabricated_fair_value_2026-10-08/` with a note. **The published
  build of 2026-10-01 carries the two invented rows.**
- **Fair values tagged with a foreign unit are dollars.** The 10-Q for 2026-03-31 prints "Prestige
  Bidco Pty Ltd ... AUD 72,042 $ 46,361 $ 49,457"; the fair value fact (49.5M) carries an AUD
  unit and was converted to 33.9M. 19 rows, 141.9M too low in that quarter.
  `foreign_unit_values: reported_in_usd`.
- **Labels from 2026-06-30 carry no percentages** ("Debt Investments Australia 1st Lien/Senior
  Secured Debt Prestige Bidco ... Industry ..."), which the fund's parser needs; issuers read
  "Reference Rate and Spread S + 5.00%" (74 rows) and the like. New label patterns for that form.
  Issuers at 2026-06-30: 389 for 784 rows (369 for 765 a quarter earlier).
- **Rate settings** (page: "Interest Rate 9.90% Reference Rate and Spread S + 6.25% (Incl. 2.75%
  PIK)"): `filed_rate_reading` all_in; `reference_rate_columns` "Reference Rate andSpread".
- **Result.** 107 outstanding to 71. 2026-03-31 goes from 201.7M over to 5.8M under.
- **Open.** Six quarters are 4.3M or 5.8M under: one tranche of Airwavz Solutions, whose member
  ends "One" and whose figures equal another tranche's, is lost in every one. A switch in the
  affiliation dedup did not bring it back and was removed; the step that drops it is not found.
  The fund's reference-rate codes (B, E and others) are not mapped: its legend was not located.

### D-060 Golub Capital Private Credit (0001930087)

- **Issuer and instrument were not split before 2026-03-31** (1,004 issuers for 1,004 rows at
  2025-12-31; now 457). Label patterns added for "Issuer, Instrument" and "Issuer | Instrument".
  About 20 labels with no separator ("Artifact Bidco, Inc. One stop 1") are not covered.
- **Rate settings** (page: "SF + 4.75 % (i) 6.23 % cash/ 2.25 % PIK"): `filed_rate_reading`
  cash_leg; `reference_rate_columns` "SpreadAboveIndex".
- **Result.** 63 outstanding to 50.
- **Open.** Four quarters are short (2023-12-31 3.5M; 2025-12-31 84.5M; 2026-03-31 84.8M;
  2026-06-30 70.1M). At 2026-06-30 every tagged position row is published (9,546.4M) and the page
  prints "Total investments ... 9,616,525": the filing tags about 70M fewer positions than it
  prints. Not the money-market funds, which the page totals separately. Not traced to rows.

### D-061 Sixth Street Lending Partners (0001925309)

- **Labels from 2026-03-31 put the column word between issuer and instrument** ("Truck-Lite Co.,
  LLC Investment First-lien loan ..."), so the issuer read "Truck-Lite Co., LLC Investment".
  New optional wrapper key `leaf_guard.issuer_trailing_strip_re`, set to drop it.
- **Rate settings** (label: "Interest Rate 8.89% (incl. 2.25% PIK)"): `filed_rate_reading`
  all_in; `principal_usd_reference` fred_h10; `reference_rate_columns` "ReferenceRate andSpread".
- **Result.** 119 outstanding to 81.
- **Open, not examined.** Totals miss in five quarters (worst 12.9M under at 2023-12-31, 5.2M over
  at 2025-09-30). C206 (13), A01 (9), B01 (8) and the spread range checks (11), counted at the
  first reading, not read.

### State of the next five

| Fund | First reading | Now | Totals within 0.5M |
|---|---|---|---|
| Ares Strategic Income | 46 | 23 | 13 of 14 |
| Goldman Sachs Private Credit | 107 | 71 | 7 of 13 |
| Golub Capital Private Credit | 63 | 50 | 8 of 12 |
| Sixth Street Lending Partners | 119 | 81 | 9 of 14 |
| Oaktree Strategic Credit | 74 | 42 | 14 of 14 |
| **Total** | **409** | **267** | **51 of 67** |

Sandboxes `n2a` and `n3a`; the five have not been run together since the changes. No disposition
has been proposed for these funds. What is fixed so far is label parsing, rate reading and three
totals errors; the rule-by-rule reading on the page that the first five had is still to do.

## 2026-10-08 (night, 4): next five funds, the totals gaps traced

Owner instruction: clear the blockers, then move on, with standing permission to download filings.
Sandboxes `n5b`, `n5c` (the five together). Not run: the full suite, the semantic diff, any 70-fund
build. Published data is unchanged.

### D-062 Sixth Street (0001925309): two totals gaps, both a single row

- **2023-12-31, 12.9M under.** The filer's label for one equity row has no issuer: "Equity and
  Other Investments Healthcare 128,321 Ordinary Shares Initial Acquisition Date 3/24/2023". The
  extractor dropped it (the issuer began with a number). The page prints the issuer: "Healthcare
  Raptor US Buyer II Corp. (8)(10) 128,321 Ordinary Shares 3/24/2023 12,875 12,875". The same
  unnamed label occurs at 2023-03-31 to 2023-09-30 (ten share classes each) and 2024-12-31.
  Fix: `staging.issuer_bridges` in the wrapper, 32 exact labels, each given the printed issuer.
  The loader read bridges only for the `issuer_bridge` strategy; it now reads them for any.
  The promoted rule `add_healthcare_ordinary_shares_2024q4` (it added the 2024-12-31 row under
  the issuer "Healthcare Ordinary Shares") is superseded and moved to
  `agent_investigate_rules/_pulled_superseded_2026-10-08/`.
- **2025-09-30, 5.2M over.** One member, Green Shoot BidCo at "Interest Rate 8.66%", carries a
  2025-09-30 fair value of 5,246 and no cost or principal. The page prints one row for the loan at
  2025-09-30 (7.78%, value 5,936); 8.66% and 5,246 are the 2024-12-31 comparative row. New rule
  `1925309/exclude_2025q3_green_shoot_comparative_fair_value`, pinned to that member and quarter.
- **Labels.** 2026 equity labels start "Equity Investments" (was "Equity and Other
  Investments"); the prefix pattern now takes both. A share count between issuer and instrument
  ("Raptor US Buyer II Corp. 128,321 Ordinary Shares") is stripped from the issuer.
- Re-run: `python scripts/v05_evidence/filing_grep.py 1925309 000095017024016336 html "128,321"`;
  `... 000119312525266848 html "EUR 5,107" 12`. Tests: `tests/test_page_labelled_contexts.py`.

### D-063 Goldman Sachs (0001920145): the lost tranche

- **Cause.** The filer tags two real tranches of Airwavz Solutions with equal issuer, instrument,
  principal, cost and value, on members that differ only in a trailing "One" / "Two". Two
  duplicate filters fold rows that agree on those fields: the affiliation filter in staging and
  the dimension-path filter in the unified build. The second one dropped the row; the first
  attempt (staging only) had no effect for that reason.
- **Fix.** New optional wrapper key `staging.distinct_member_suffix_re`. Its match on the raw
  member joins both filters' keys. Set for Goldman Sachs to the number words One to Ten at the
  end of the member. A member on two affiliation paths still folds to one row (tested).
- **Evidence.** Page, 2026-06-30: two rows "Airwavz Solutions, Inc. ... 9.07 % S + 5.25 % 03/31/27
  5,817 5,793 5,759". Published was 4.3M to 5.8M under the filed total in six quarters, the value
  of the one row.

### D-064 Golub (0001930087): positions tagged on a subtotal context

- **Cause.** In the 10-Qs from 2025-12-31, a schedule row that is the only position in its
  industry and type group has no investment-identifier member. Its facts sit on the group's own
  context (industry, affiliation, type), the context a multi-row group uses for its subtotal. The
  instance holds the value, cost, principal and rate but not the name. 18 rows a quarter: 84.5M,
  84.8M and 72.8M at 2025-12-31, 2026-03-31 and 2026-06-30. The 10-K tags every row.
- **Fix.** New module `pipeline/page_labelled_contexts.py`, switched on by the wrapper key
  `source_encodings.page_labelled_contexts` (axis combinations). A context with exactly that axis
  set is read as a position when exactly one printed row carries its fair-value tag and the row
  starts with a label, not an amount and not "Total". The identifier is the row's first two text
  cells ("Star Holding, LLC | Senior secured"). Subtotal rows print amounts only and are never
  adopted. The extractor, source reconciliation and the PIK and non-accrual evidence extractors
  read contexts through one function (`bdc_filings.parse_filing_contexts`) so they agree. The
  source-fact cache key takes the filer's setting, so other filers' caches stay valid.
- **Second item.** The affiliate roll-forward table tags one issuer's closing value on the
  identifier axis with the issuer name alone ("RW AM Holdco LLC" 2,631, the sum of its four
  schedule rows). New structural rule `1930087/exclude_affiliate_rollforward_issuer_only_rows`,
  the same pattern as Blue Owl's.
- **2023-12-31, 3.5M under: as filed.** The printed Containers and Packaging rows sum to 32,366;
  the printed subtotal is 35,834. Principal and cost are short by 3,482 and 3,450. The prior
  quarter lists an eighth row, WP Deluxe Merger Sub (par 3,491). The 2023-12-31 schedule neither
  prints nor tags it but its subtotal includes it. Nothing to extract.
- Re-run: `python scripts/v05_evidence/page_labelled_dry_run.py 1930087`;
  `python scripts/v05_evidence/page_row_contexts.py 1930087 000193008726000099 2026-06-30`;
  `python scripts/v05_evidence/page_block_sums.py 1930087 000193008724000010 2023-12-31`.
- **Limits.** The rule reads the first two text cells; a filer with another column order needs
  its own check. The page reader that confirms printed fields keys on identifier members, so
  these rows have no printed-field confirmation yet.

### D-065 Ares Strategic Income (0001918712): 2025-03-31, 28.7M under

- **31.2M: a misdated context.** The 2025-03-31 schedule row "Grant Thornton Advisors LLC First
  lien senior secured loan 7.07 % SOFR (M) 2.75 % 06/2031 31,393.4 31,461.1 31,206.9" is tagged
  on context c-285, dated 2024-12-31. The filing's 2024-12-31 schedule has its own two Grant
  Thornton rows on other contexts. The row read as a comparative and left the quarter.
  Fix: new wrapper key `source_encodings.misdated_contexts`
  ("0001918712-25-000030 c-285 2024-12-31 -> 2025-03-31"); the parser re-dates the context, so
  the row keeps every tagged fact. A listing whose filed date does not match is left alone.
- **2.5M over: as filed.** The 226 printed Investment Funds and Vehicles rows sum to 707,193.1;
  the printed subtotal is 704,669.0. The rows are published as tagged.
- **Not a gap.** Two issuer-only members (Fitness Ventures 54.67M, OPH NEP 40.56M) are the
  affiliate roll-forward closing values; their schedule rows sum to the same amounts and the
  issuer-only rows are already dropped.
- Re-run: `python scripts/v05_evidence/page_heading_sums.py 1918712 000191871225000030 2025-03-31`
  against `python scripts/v05_evidence/page_axis_facts.py 1918712 000191871225000030 2025-03-31
  EquitySecuritiesByIndustryAxis`.

### D-066 Goldman Sachs: reference-rate codes from the filer's own legend

- The schedule note defines the codes. To 2024-06-30: LIBOR "L", Euribor "E", SOFR "S", SONIA
  "SN", NIBOR "N", CDOR "C", BBSW "B", Prime "P". From 2024-09-30: CORRA "C", SARON "SARON". From
  2025-09-30: STIBOR "STIBOR". At 2026-06-30: BBSW "BW", BBSY "B". Set as
  `reference_rate_codes`, with dates for C and B.
- Before this, rows printed B, C, N, SN, SARON and STIBOR kept a guessed SOFR (about 200 rows).
- **Disagreement to know about.** From 2025-12-31 the filer also tags each row's benchmark. At
  2026-06-30, of the rows printed "B", 14 are tagged BBSW and 7 BBSY; the legend says BBSY. The
  legend is used. "BY" is not in the legend; its two rows are tagged BBSY.
- Re-run: `python scripts/v05_evidence/rate_code_enum.py 1920145 000119312526340582`;
  `python scripts/v05_evidence/filing_grep.py 1920145 000119312526340582 html "Euribor (" 1 400`.

### D-067 Three more extraction gaps, fixed

- **Sixth Street net investment income was the incentive fee** (2025-03-31: 21,359 published,
  152,562 printed; same at 2025-06-30). The income concept map matches by substring, and the
  filer's own concept `IncentiveFeesOnNetInvestmentIncome` comes before `us-gaap:NetInvestmentIncome`.
  Fix in `pipeline/bdc_fund_income.py`: a concept naming both an incentive fee and net investment
  income is never net investment income; the expense itself maps to the incentive fee.
  **This is shared code, not a wrapper setting.** Its effect on the other 65 funds is not
  measured (no semantic diff was run). A scan of cached filings found such concept names in ten
  funds outside the cohort, none of them a net investment income figure (payables, percentages).
- **Goldman Sachs foreign principal had no dollar value** (FX01, 13 quarters):
  `principal_usd_reference` fred_h10 in the wrapper.
- **Sixth Street issuer names kept the whole label** for notes, partnership units and preference
  shares (C206, 12 quarters): instrument markers added to the wrapper.
- Result: 273 outstanding to 246.

### D-068 Sixth Street reference-rate codes: set, and only partly effective

- The schedule note defines them (10-K 2023-12-31 onward): Euribor "E", SOFR "SOFR", SONIA "S",
  NIBOR "N", STIBOR, Prime "P"; CORRA "C" from 2025. The filer's row tags from 2025-09-30 agree
  (11 rows printed "S" are tagged SONIA). Set as `reference_rate_codes`.
- **Effect:** N and STIBOR rows now read correctly (22 rows). **Not fixed:** rows printed "S" still
  publish SOFR (12 rows read; the filer says SONIA), and rows printed "C" still publish a guessed
  SOFR (Cast & Crew, CAD, 37.6M to 98.9M). The page reader finds this fund's reference column in
  only some filings (many rows read "blank"). Open defect.

### D-069 Proposed dispositions for the next five (not accepted)

- `scripts/v05_evidence/make_proposed_dispositions.py n5e --write` writes
  `data/overrides/finding_dispositions_proposed/next5_2026-10-08.json` and
  `docs/investigations/next5_proposed_dispositions.md`. The ledger does not read that directory.
- 30 proposals. 19 are the first five's reasons (negative cost or value on undrawn lines,
  principal above value, no rate in the source, quarters before the first schedule), proposed only
  for fund-quarters where the row-by-row check passes on sandbox `n5e`. 11 were read this session
  and quote the page or the tags.
- If the owner accepted all of them the five funds would stand at 109 outstanding, from 246.
- The owner has not accepted any. The scope in `findings_scope.ciks` is unchanged.

### State of the next five (sandbox `n5e`, the five built together from empty)

| Fund | First reading | Start of this session | Now | If proposals accepted | Totals within 0.5M |
|---|---|---|---|---|---|
| Ares Strategic Income | 46 | 23 | 23 | 15 | 13 of 14 |
| Goldman Sachs Private Credit | 107 | 71 | 64 | 15 | 13 of 13 |
| Golub Capital Private Credit | 63 | 50 | 49 | 17 | 11 of 12 |
| Sixth Street Lending Partners | 119 | 81 | 68 | 46 | 14 of 14 |
| Oaktree Strategic Credit | 74 | 42 | 42 | 16 | 14 of 14 |
| **Total** | **409** | **267** | **246** | **109** | **65 of 67** |

The two fund-quarters outside 0.5M are as filed (D-064, D-065): the filer's printed rows do not
add to its printed subtotal.

**Not cleared.** 95 findings have no proposal: 58 rule groups not read, and three rate rules
whose check fails on named rows. Known real defects left in place:

- Sixth Street: "S" and "C" reference rates (D-068); the Elysium preference shares at 2024-12-31
  are added by rule and carry no class or accession.
- Ares Strategic Income: Steward Partners prints "9.08 % SOFR (Q) 4.75 %" at 2025-12-31 and
  2026-03-31 and publishes no rate.
- Oaktree: five quarters of loans with no rate (Impel, BioXcel, Verona) not read on the page.
- Goldman Sachs: rows printed "B" at 2026-06-30 follow the legend (BBSY); 14 are tagged BBSW.
- Golub: the 18 rows a quarter named from the page have no printed-field confirmation.

**Process notes.** I ran `git stash` and `git stash pop` once on the shared working tree to compare
a hash. Everything came back, but a staged rename became an unstaged delete plus a staged add. I
should not have used it there. A stray bare `python -` hung once and was killed.

**Next fund by size:** MSD Investment Corp. (0001849894), then North Haven Private Income Fund,
Monroe Capital Income Plus, Blue Owl Technology Income, Barings Private Credit. Not started.

## 2026-10-09: owner rulings on three of the proposed dispositions

Owner, in session: "on cash: fix the check, but still include cash items. pct of net assets:
check them. keep the undrawn lines."

### D-070 The fair-value conservation check compares like with like, by wrapper setting

- **Ruling.** Fix the check; cash rows stay published and stay in the published total.
- **First attempt, measured and rejected.** Comparing every investments-only anchor with the rows
  that are not cash would move 49 fund-quarters on the published build of 2026-10-01. About 20 of
  them go from reconciled to short: those filers count their cash funds inside the balance-sheet
  investments line. Whether cash sits inside that line is a fact about each filer.
- **Fix.** New wrapper key `source_encodings.investments_total_excludes: ["cash_rows"]`. For a
  filer that declares it (`scripts/shadow_conservation_engine.py`):
  - an investments-only anchor is compared with the published rows that are not cash;
  - the cash rows are checked against the filed cash-equivalents figure, which they may not
    exceed; where none is filed the result says `cash_status = no_filed_figure`;
  - the investments-plus-cash anchor is used only when the filed cash figure equals the
    schedule's cash rows.
  `value_sum` is unchanged (it includes cash). New result columns: `compared_sum`, `cash_sum`,
  `filed_cash`, `cash_status`. Fair value only. Every other fund is unchanged.
- **Declared for** Goldman Sachs (balance sheet, 2025-06-30: "Investments, at fair value ...
  9,630,944" and on its own line "Investments in affiliated money market fund ... 233,261") and
  Oaktree (schedule, 2025-06-30: "Cash and Cash Equivalents and Restricted Cash $ 471,299" and
  "Total Portfolio Investments, Cash and Cash Equivalents and Restricted Cash $ 6,834,225", which
  is 6,362,926 of investments plus that figure; the schedule's one fund row is 100.7M of it).
- **Measured on the published build, read-only:** five fund-quarters change, all from failing to
  reconciled: Goldman Sachs 2025-06-30, 2025-09-30, 2025-12-31; Oaktree 2025-06-30, 2025-09-30.
  In the sandbox the six findings are gone and the two proposals for them are withdrawn.
- **Residual.** Goldman Sachs files no cash-equivalents figure the pipeline reads, so its money
  market row (156M to 518M) is published but checked against nothing. The result says so.
- Re-run: `git show 8bf71b0:scripts/shadow_conservation_engine.py > before.py`, then
  `python scripts/v05_evidence/conservation_like_for_like_effect.py before.py`.
  Tests: `tests/test_agent_promoted.py -k engine` (five new or changed).

### D-071 Percent of net assets: every failing row read on the page

- 60 Golub rows in 12 filings and 27 Sixth Street rows in 9 filings fail the identity. Each is
  published with exactly the percent and the fair value the page prints and tags. The percents
  are the filers' own, printed to one decimal and often one step off what the value implies
  (Golub 2025-12-31, AQA Acquisition Holding: printed 0.6 on 24,058, which implies 0.54).
- The proposals stay proposals, now with this evidence. The owner asked for the check, not yet
  for acceptance.
- Re-run: `python scripts/v05_evidence/pct_rows_on_page.py n5e 1930087` and `... 1925309`.

### D-072 Goldman Sachs members with no fair value: accepted

- Owner: "keep the undrawn lines". Read as: accept the proposed disposition for Goldman Sachs
  oracle rule B01 (position contexts with no value: undrawn commitments printed with a par amount
  only, and members defined for other facts). If the owner meant "publish those lines as rows",
  this entry is the wrong action and should be withdrawn: it changes no data either way.
- Recorded in the live store as `DS-N5-B01-1920145`
  (`data/overrides/finding_dispositions/next5_owner_accepted.json`), five quarters named.
  Four findings close; one stays open because an earlier fix for it is staged.

### State (sandbox `n5e`, check stages re-run)

| Fund | Before these rulings | Now | If the remaining proposals were accepted |
|---|---|---|---|
| Ares Strategic Income | 23 | 23 | 15 |
| Goldman Sachs Private Credit | 64 | 56 | 15 |
| Golub Capital Private Credit | 49 | 49 | 17 |
| Sixth Street Lending Partners | 68 | 68 | 46 |
| Oaktree Strategic Credit | 42 | 40 | 16 |
| **Total** | **246** | **236** | **109** |

27 proposals remain (19 on a check, 8 on a reading). Not run: the full suite, the semantic diff,
any 70-fund build. Published data unchanged. Uncommitted.

### D-073 Standing instruction: an accepted reason may be accepted by its check

- Owner, in session 2026-10-09: "yes, a disposition i already accepted may be accepted by its
  check". Asked because every proposal for the next five had been sent for approval one by one.
- **What it covers.** A reason the owner has already accepted for some fund, restated as a
  deterministic row-by-row check. On another fund, a fund-quarter where that check passes is
  accepted without asking. Today that is five reasons, the first five's DS-003 to DS-007:
  quarters before the first schedule (F28), negative cost on undrawn lines (C107), principal far
  above value (X06), no rate in the source (X02), negative value on undrawn lines (C103).
- **What it does not cover.** A new reason; a reason supported only by a reading; a fund-quarter
  where the check fails (it stays open and the rows are read); anything that changes shared
  code; widening `findings_scope.ciks`. New reasons are collected and brought to the owner in one
  batch per group of funds, grouped by reason.
- **Applied.** 19 entries for the next five moved to the live store
  (`data/overrides/finding_dispositions/next5_owner_accepted.json`, ids `DS-N5-...`), each
  recording the check and this decision as its acceptance. With the owner-accepted B01 entry the
  file holds 20 entries naming 104 fund-quarters.
- **Limits to remember.** The "published equals the tag" check cannot see a wrong tag. The F28
  check (quarter earlier than the fund's first published schedule) is computed in
  `make_proposed_dispositions.py`, not in `pipeline/disposition_validity.py`. An entry does not
  close a finding that an earlier reviewer marked a confirmed error; the first five's X02 entries
  carry a flag for that, these do not, so 17 such findings stay open for a reading.
- AGENTS.md is not edited (owner only); it still says an agent may propose and a deterministic
  check or the owner accepts, which this instruction is consistent with.

## 2026-10-09 (later): the unread findings of the next five, read

Owner: "commit, then read the 95 unread findings". Commit 65fddd9. Sandboxes `n5f` to `n5h`.
Not run: the full suite, the semantic diff, any 70-fund build. Published data unchanged.

### D-074 What the reading found, and what was done

**Fixed in a wrapper or in shared code**

- **Oaktree issuer names (every quarter to 2026-03-31).** The label is "Issuer, Instrument" and
  the issuer was never split from it: 368 "issuers" for 368 rows at 2025-09-30. The continuity
  check caught it only when the 2026-06-30 label changed form (5 pct of names carried over).
  Fix: `staging` patterns in the wrapper. Now 162 issuers for 368 rows; continuity passes.
  **The published build has the unsplit names.** I reported Oaktree as "14 of 14 totals" without
  looking at its issuer names; totals cannot see this.
- **Gross-asset check and cash rows.** The check had the same cash problem as the conservation
  check (D-070). `pipeline/validate_holdings.py` now applies the same wrapper declaration: for a
  declared filer the published cash rows are added to the filed investments, up to the filed cash
  figure. Other filers unchanged. 12 findings gone (Goldman Sachs 9, Oaktree 3).
- **`maturity_date` can now be set by a row correction** (`pipeline/unified_holdings.py`).

**Corrected from the page, row by row** (`data/overrides/row_corrections.csv`, 30 values on 11
rows; specs in `scripts/v05_evidence/make_row_corrections.py`, each with the printed line)

| Fund, quarter | Row | Published before | Page | Cause |
|---|---|---|---|---|
| Goldman Sachs 2025-06-30 | Berkeley Research Group | cost 854K | 8,540 | printed "8,54 0", the tag took 854 |
| Goldman Sachs 2025-09-30 | 123Dentist | maturity 2002-08-08 | 08/08/29 | printed "08/08/2 9", page reading took 2002 |
| Sixth Street 2023-12-31, 2024-09-30 | ASP Unifrax (two rows) | principal negative | 1,130 and 1,993 | tag sign |
| Sixth Street 2024-12-31 | Flight Intermediate HoldCo | floating, SOFR | fixed 11.50 % | member text says "SOFR +" |
| Sixth Street 2025-06-30 | X Holdings | floating, SOFR | fixed 9.50 % | member text says "SOFR +" |
| Sixth Street 2024-12-31 | Price Fx | maturity 2024-10-31 | due 10/2029 | member says "due 10/2024" |
| Oaktree 2023-09-30 | Impel Pharmaceuticals term loan 1 | no rate | SOFR + 10.75 %, 16.06 % | no rate tag |
| Ares Strategic Income 2025-03-31 | WRE Sports | spread 5.5, SOFR | 11.00 % (5.50 % PIK), fixed | PIK tagged as spread in one filing |
| Ares Strategic Income 2025-12-31, 2026-03-31 | Steward Partners "first lien loan" | a loan with no rate | warrant, 138,674 units, cost 2,644.6 | member names a loan |

**Read and proposed as a disposition** (new reasons, for the owner; in
`docs/investigations/next5_proposed_dispositions.md`)

- Sixth Street subtotal arithmetic (9): the check adds current and comparative rows together.
- Sixth Street holdings against total assets (4): the filed investments figure is missing from
  the fund-level data for 2023-06-30 and 2023-09-30; published equals the printed total exactly
  (1,758,911 and 2,048,389).
- Oaktree euro rows (3): rows of the joint venture's own schedule, kept and not published.
- Oaktree loans with no rate (4 quarters), Ares Strategic Income rows with no rate (4 quarters),
  Goldman Sachs loan with a printed cost of 1, Ares Strategic Income 27.20 % CLO rate, Golub
  equity rows with no unit count, Golub's two year-end filings.

**Real defects found and left open**

- Golub 2023-06-30 fund-level figures are wrong (published net assets 50,000; the page prints
  total assets 653,733 and net assets 650,323, in thousands). The fund had not started
  investing; there are no holdings that quarter. Five findings.
- Oaktree 2022-03-31: share count is filed in thousands (4,000), so net asset value per share
  reads 25,040. No holdings that quarter.
- Sixth Street 2024-12-31: the distribution per share is the full-year figure (2.53), not the
  quarter's.
- Sixth Street: the filed investments figure is missing from fund-level data for two 2023
  quarters.
- Sixth Street Elysium preference shares (2024-12-31) and Golub's two money market rows
  (2025-12-31) are added by rule and carry no accession or class. Seven findings.
- Sixth Street reference rates "S" and "C" (D-068), still open.

**Not read** (listed in the proposals file): the launch-quarter heuristics (F16, F25, F26), Ares
Strategic Income income identity and one rate convention row, Oaktree's derivative finding and
one comparative-row finding, two non-accrual findings whose earlier fix was pulled, and the
findings an earlier reviewer marked as confirmed errors where the check-based entry does not
override the verdict.

## 2026-10-09 (evening): two checks repaired, defects fixed

Owner: "commit, repair the two checks, then fix the defects". Commit eaccc65. Sandbox `n5i`.
Not run: the full suite, the semantic diff, any 70-fund build. Published data unchanged.

### D-075 What was changed

**The two checks (shared code, every fund; effect measured read-only on the published build)**

- **Subtotal arithmetic (oracle A01).** It summed a subtotal's rows across the current and the
  comparative period. It now takes the rows of the subtotal's own period. Published build: 39
  fund-quarters go from failing to passing, none the other way (117 failures to 78).
- **Holdings against filed investments (oracle A04, E01).** With no investments figure filed it
  compared holdings with total assets inside a 5 pct band, which a correct schedule fails. My
  first repair skipped the check there; measured, that would also have stopped flagging funds
  whose holdings are half of total assets. It now keeps total assets as a stand-in with a
  one-sided band: fail above 105 pct or below 70 pct of total assets. **The 70 pct floor is a
  judgement, not a measured bar.** Published build: 18 fund-quarters go from failing to passing,
  none the other way; funds near 50 pct still fail.
- Re-run: `git show eaccc65:pipeline/oracle_checks.py > before.py`, then
  `python scripts/v05_evidence/oracle_check_effect.py before.py`.

**Defects fixed**

- **Fund-level figures corrected from the page.** New `figure_corrections` in the fund-level
  wrapper (`data/overrides/fund_highlights_wrappers/`, each with its evidence), applied before
  scale detection.
  - Golub 2023-06-30: net assets 650,323K, total assets 653,733K, liabilities 3,410K. Company
    facts keep the last value filed for a date, and a later 10-K files 50,000 for this one.
  - Oaktree 2022-03-31: 4,000,000 shares at 25.04. The first 10-Q files both in thousands.
  - Sixth Street 2023-06-30 and 2023-09-30: investments 1,758,911K and 2,048,389K, the printed
    "Total Investments". No undimensioned fact is filed for those dates.
- **Golub money market rows.** They were published in one quarter only, by a rule that added
  them as cash (81.8M at 2025-12-31). That rule's own record shows the gap to the filed total
  going from 84.5M to 2.7M: cash rows covering for missing positions. The cause: the filer tags
  their fair value with its own concept. New wrapper key `source_encodings.fair_value_concepts`
  (read for this filer only; 17 funds have a concept of that name). The rows are now published as
  cash in every quarter, named in `cash_identifiers`, and Golub declares
  `investments_total_excludes`. The rule is pulled.
- **Sixth Street Elysium preference shares (2024-12-31).** The page prints a fair value of
  49,063; only the cost is tagged. New wrapper key `source_encodings.untagged_values`; a missing
  value is filled, a tagged one never replaced. The row now has its accession and class. The rule
  that added it by hand is pulled.
- **Sixth Street reference rates.** Two causes in the page reader, both fixed in shared code:
  the shared reading of "S +" as SOFR ran before the filer's own code (its note: "SONIA or S"),
  and rows shifted one column off their header were not read. On Sixth Street's pages 414 rows
  now read (196 SOFR, 169 EURIBOR, 44 SONIA, 5 CORRA) and 11 change from SOFR to SONIA.
  **Measured on the first five funds' pages: no reading changes.**

**Not defects after all** (I had listed them as defects)

- Sixth Street's distribution per share at 2024-12-31 (2.53) is the filed year figure (4.54) less
  the filed nine-month figure (2.01). As filed.
- Sixth Street's missing 2023 investments figure was never tagged by the filer; now supplied
  from the page as above.

**New wrapper keys this round:** `fair_value_concepts`, `untagged_values` (holdings wrapper);
`figure_corrections` (fund-level wrapper). The source-fact cache key takes them, and other
filers' keys are unchanged (checked on one CIK).

### D-076 The total-assets stand-in floor is 85 pct (owner ruling)

- Owner, 2026-10-09: "70% seems low", then, after the measurement below, "let's roll with that"
  (85 pct).
- **Measured** on the published build of 2026-10-01, the 886 wrapper fund-quarters that file both
  figures: filed investments over total assets has a median of 95 pct, 25th percentile 92 pct,
  10th percentile 85 pct, 5th percentile 75 pct. By band: 727 at 90 pct and over, 71 at 85 to 90,
  26 at 80 to 85, 28 at 70 to 80, 34 below 70.
- **Why not 100 pct:** total assets also hold cash and receivables, so a correct schedule sits
  below them. The exact comparison is the conservation check (0.5 pct band against the filed
  investments figure, or the filer's printed schedule total where none is filed).
- **Effect on the published build, read-only:** oracle A04 goes from 138 failures to 126; 12
  fund-quarters go from failing to passing and none the other way (it was 18 at 70 pct).
- **Standing consequence.** A fund-quarter with no filed investments figure that fails the floor
  gets its printed "Total Investments" supplied through the fund-level wrapper
  (`figure_corrections`), not a disposition. 39 fund-quarters in 11 funds file no investments
  figure today.
- `pipeline/oracle_checks.py` (`_TOTAL_ASSETS_FLOOR`), `tests/test_oracle_checks.py`.

### D-077 Next five: the unread findings read; defects found by reading fixed (2026-10-09, night)

Owner instruction: "commit, read the unread findings, then keep iterating over funds from smallest to
largest ... fixing each of the ledger items, keeping human review items for the end."

Sandbox `n5j`. Next five: 92 outstanding to 82, all 82 read and covered by a reading-based proposal
(34 entries, `docs/investigations/next5_proposed_dispositions.md`); none accepted. Totals unchanged
(65 of 67 fund-quarters within 0.5M; the two others as filed).

**Fixed (real errors):**

- **Sixth Street, issuer names.** 460 published rows carried the schedule heading on the issuer name
  ("Debt Investments Business Service Galileo Parent, Inc."). No rule flagged it. Cause: the filer's
  own headings (Communications, Internet Services, Manufacturing, Human Resource Support Services,
  Hotel, Gaming, and Leisure, Other) and its misspellings (Business Service, Busines Services,
  Automative, a doubled prefix, "DebDebt") were not in the shared label list. They are now spelled
  out in the fund's own leaf-guard prefix (`0001925309.json`). 460 rows to 1.
  The same defect is in the published build for Sixth Street Specialty Lending (0001508655, 1,015
  of 2,573 rows); its wrapper is not changed here. The leaf-guard prefixes of the four leaf-guard
  funds are applied in a chain, so the new headings also strip from 0001508655's rows on its next
  build. Not measured on that fund.
- **Reference rates read as SOFR.** Golub's sterling, Australian and Canadian loans, and the Nordic,
  Swiss, Australian and Japanese loans of Ares Strategic Income and Oaktree, published "SOFR"
  because the filer's printed codes were not declared. `reference_rate_codes` added from each
  filer's legend (Golub: SF, SN, E, P, L, C, CA, A; A = BBSW from footnote "Three-Month AUD ...
  4.42 %"). At 2025-12-31: Golub 27 rows, Ares Strategic Income 11, Oaktree 6 change.
- **Row corrections from the page** (`row_corrections.csv`, D-077): Sixth Street 2023-03-31 two
  spreads the member label misstates (7.25, 7.50); Ares Strategic Income, three rows in two
  quarters whose label carries a loan's rate terms on an equity or undrawn row; AX VI VET loan 5
  at 2026-06-30, rate and PIK tags swapped.
- **Fund income (shared code, `pipeline/bdc_fund_income.py`).**
  (a) `us-gaap-supplement:InvestmentIncomeOperatingAfterExpenseAndTax` is read as net investment
  income where a period has an income statement and no net investment income fact. Ares Strategic
  Income's first two 10-Qs tag only that; its 2023-12-31 quarter then fell back to the annual
  figure divided by four (17.4M; now 33.3M = 69.4M less three filed quarters). A period known only
  by that fact makes no row.
  (b) A first period shorter than two months is no longer scaled to three months. Ares Strategic
  Income's 2022 stub published 549K of income against the filed 183K. Published build: 20 such
  periods in 20 funds.
- **Derivatives (shared code, `pipeline/bdc_derivatives.py`).** Each fact is counted once, only the
  least-dimensioned contexts are read, and a parent member is not added to its parts. Oaktree
  2025-06-30: 3,000M notional and 45.2M to the printed 750M and 15.1M. Measured on the 1,004 cached
  filings of the 77 wrapper funds: 281 type-quarters change in 24 funds. Only Oaktree's were read
  against the page. `bdc_derivatives.csv` is not a published holdings field.
- **Re-verifier:** a value declared in `untagged_values` is checked against the declaration
  (`provenance_reverify.py`); the 49.1M Elysium row no longer reads as "no source tag".
- **Golub:** `pik_only_tag_reading: coupon` (Super REGO, printed "N/A 15.00 % PIK", published no rate).

**Read and proposed (owner to accept; nothing closed):** Sixth Street A01 in eight quarters (the
filer's subtotal and row tags name different headings; holdings equal the printed total);
launch-period heuristics F16, F25, F26, F33; X02 rows printed with no rate; non-accrual flags;
18 findings that carried an earlier reviewer's "real error" verdict, each now a proposal that
replaces the verdict with the filing line (new `SUPERSEDES` table in the generator).

**Open, not fixed:**

- Loans whose coupon is tagged only as PIK and that also carry a spread (22 HoldCo, Ares Strategic
  Income; the same pattern was accepted as filed for Ares Capital, DS-006A) publish no all-in
  rate. A convention question for the owner; changing it changes the first five.
- Oaktree, Delta Leasing: labels of two rows swapped at 2024-12-31 (2K), unit counts of two rows
  wrong at 2025-06-30. Values right.
- The stub-period and after-tax changes, the derivative change and the chained leaf-guard prefix
  are shared code: effect on other funds measured only as stated above.
- The sandbox's sector step called an OpenAI endpoint for industry labels and got "no credits".
  Not an SEC call; it is existing pipeline behaviour that a sandbox run triggers.

**Tests:** `test_bdc_fund_income.py` 33, `test_bdc_derivatives.py` 20, `test_page_labelled_contexts.py`
and `test_provenance_reverify.py` 81, and the wrapper, bridge, encoding and staging files 863,
all pass. **Not run:** full suite, semantic diff, any 70-fund build.

### D-078 Smallest-first batch 1: Saratoga, NexPoint Capital, SCP, PIMCO Capital Solutions, BlackRock Direct Lending (2026-10-09, night)

Owner instruction: "keep iterating over funds from smallest to largest". Read literally: the cohort
ranked by published fair value at 2026-03-31, smallest first (`scripts/v05_evidence/cohort_by_size.py`;
77 CIKs in the manifest). Earlier batches went largest first; the owner may have meant that order.

No 2026-06-30 filings are cached for these funds and none were downloaded: the batch runs to
2026-03-31 (Saratoga to 2026-05-31). Chain: `scratch/2026-10-07_printed_rates/run_batch.sh`.

Sandboxes `s1a` (as published) to `s1c`. Outstanding 520 to 329; 274 with the reasons the owner
already accepted applied by their checks (`small1_accepted_by_check.json`, 12 entries, D-073).
Nothing else is dispositioned: the 274 are not read.

| Fund | Published against filed, as published | Now (s1c) |
|---|---|---|
| Saratoga (0001377936) | 336M to 514M over in six quarters, 65M over in one | within 0.5M in four of seven; +0.9M, +2.2M, -5.0M in three |
| NexPoint Capital (0001588272) | 23.5M under in two quarters | equal in all twelve |
| SCP Private Credit Income (0001743415) | no usable filed figure; 10M to 21M over the printed total in four quarters | equal to the printed total in all eleven |
| PIMCO Capital Solutions (0001905824) | 19M to 75M under in ten of eleven quarters | within 0.5M in eight, counting Treasury bills; +2.8M, +1.9M, -0.8M in three |
| BlackRock Direct Lending (0001834543) | 0.7M under in one quarter | unchanged |

**Causes and fixes (each in the fund's wrapper; shared code only where named):**

- **Saratoga.** (a) 233 to 335 rows a quarter are the loans of its own CLO, tagged with the CLO as
  legal entity; published as the fund's positions. `legal_entity_members` now classes them as the
  CLO's own schedule (kept, not published). (b) The joint venture's two positions ("Unsecured
  Loan", "Membership Interest", about 20M) were read as subtotals; two leaf markers added.
  (c) The 10-K for 2025-02-28 tags the Healthcare Services subtotal (85.1M) on a loan's label with
  the industry appended; `category_marker_re` extended.
- **NexPoint Capital.** In the 10-Qs for 2025-06-30 and 2025-09-30 ten of the printed positions
  carry no identifier member. New wrapper key `source_encodings.context_identifiers`
  ('ACCESSION CONTEXT => IDENTIFIER'; shared code in `page_labelled_contexts.py`,
  `bdc_filings.py`, `source_encodings.py`, schema) names them as the filer names them in its other
  filings. 20 entries drafted by `unnamed_position_rows.py` and read against the page.
- **SCP.** (a) A heading tagged with a value ("Preferred Equity - 5.2%") published as a position;
  `category_marker_re` extended. (b) Rows of the affiliate roll-forward note published as
  positions; rule `1743415/exclude_affiliate_rollforward_rows` (the Golub precedent of D-066).
  (c) Company facts hold the affiliate note's total as the fund's investments; the printed
  "Total Investments" is supplied for eleven quarters (`fund_highlights_wrappers/0001743415.json`).
- **PIMCO Capital Solutions.** Rows named by issuer alone ("... | GCOM | 17% | 02/16/2029") were
  read as subtotals. New wrapper key `dispatch.leaf_marker_re` (shared code in
  `bdc_xbrl_wrapper.py`, schema): a row ending with a maturity date is a position. Treasury bills
  now publish as cash in every quarter (they did from 2024-12-31 only). An existing test expected
  the warrant under the debt heading to be a category rollup; it was excluded and the fund
  published short, so the expectation is changed.
- **BlackRock Direct Lending.** `filed_rate_reading: all_in`: the label states "Total Coupon 10.28%"
  and the rate fact is that figure. 9 to 25 rows a quarter published no rate; now 2.

**Open on these five (not fixed):** Saratoga's three small differences and issuer names that keep a
percent prefix ("229.3% - Innergy, Inc.- Custom ..."); PIMCO's three small differences; BlackRock,
two rows whose rate fact is not the label's total coupon; the 274 unread findings.

**Tests:** wrapper, encoding, page-context, promoted-rule and fund-level wrapper files pass (654,
63, 575 in the runs made). **Not run:** full suite, semantic diff, any 70-fund build.

### D-079 Smallest-first batch 2, first reading: TCW Star, Onex, TriplePoint Private Venture, Audax, Stellus Private Credit (2026-10-09, night)

Sandbox `s2a`, as published plus the shared fixes of D-077 and D-078. 386 outstanding; 346 with
the reasons the owner already accepted applied by their checks (computed, not written). Not read
beyond the totals below.

- **TriplePoint Private Venture (0001792509), Stellus Private Credit (0001901037):** published
  equals filed in every quarter.
- **Audax (0001633858):** 1.2M under in one quarter (2025-09-30). Not read.
- **TCW Star (0001916608):** no filed investments figure in eight quarters; the printed
  "Total Investments" includes Treasury bills and a money market fund, which are not published.
  Published debt equals the printed debt subtotal where read (2023-03-31: 36,507 thousand).
  **One real error fixed:** at 2025-06-30 the Superior Industries delayed draw loan is tagged with
  scale 3 on a schedule printed in dollars and published 72.5M for a 72,532 dollar position, so
  the fund published 270.1M against a printed 203.1M. Row correction from the page
  (`row_corrections.csv`). Not yet rebuilt.
- **Onex (0001860424):** 26.4M under at 2023-03-31. Three tagged rows (Connect America term
  facility 20,516 and incremental 1,212; S4T equity units 287) have no published row. Cause not
  found; about 4.4M more is unexplained.

Next by size after these: Manulife Private Credit 0001988280, Silver Capital Holdings 0001674760,
TCW Direct Lending 0001603480, Senior Credit Investments 0001959568, Commonwealth Credit Partners
0001841514.

### D-080 Largest-first, third batch: MSD, North Haven, Monroe, Blue Owl Technology Income, Barings Private Credit (2026-10-09/10)

Owner correction 2026-10-09: "i meant largest first. commit, then keep going". The two
smallest-first batches (D-078, D-079) were a misreading of the order; their fixes are committed
(ae19926) and those funds are parked.

Sandboxes `l3a` (as published plus earlier shared fixes) to `l3d`. No 2026-06-30 filings are cached
for these funds and none were downloaded; the batch runs to 2026-03-31.

Outstanding 550 to 349; 263 with the reasons the owner already accepted applied by their checks
(`large3_accepted_by_check.json`, 16 entries, D-073). The 263 are not read.

| Fund | Published against filed, as published | Now (l3d) |
|---|---|---|
| Monroe Capital Income Plus (0001742313) | 38M to 273M over in ten quarters | equal in all thirteen |
| Barings Private Credit (0001859919) | 17M to 390M over in all thirteen | equal in twelve; 203.4M over at 2023-06-30 |
| Blue Owl Technology Income (0001869453) | 5M to 19M over in five quarters | equal in all |
| MSD Investment Corp. (0001849894) | 20.0M over in one quarter | equal in all |
| North Haven Private Income (0001851322) | 0.5M to 1.2M off in four quarters | equal in all |

**Causes and fixes:**

- **Monroe, Barings: the affiliate roll-forward note published as positions** (the Golub and SCP
  pattern). The note's members carry no percent of net assets and no principal. Rules
  `1742313/exclude_affiliate_rollforward_rows` (ten quarters) and
  `1859919/exclude_affiliate_rollforward_rows` (seven quarters) plus
  `1859919/exclude_affiliate_rollforward_rows_2024q4_on` (five quarters, keeping the Thompson
  Rivers member interest and unit rows, which are schedule rows there). Each rule lists only the
  quarters in which removing those rows makes published equal filed, measured on `l3a`. They are
  quarter-listed, so a new quarter needs the same measurement before the rule is extended.
- **Blue Owl Technology Income, North Haven: dollar values tagged with a foreign unit** and
  converted a second time (Armstrong Bidco: par GBP 26,570, value fact 33,618 in "GBP", published
  42,839; North Haven's Tempo Acquisition, a dollar loan, 3,999 published as 2,777).
  `foreign_unit_values: reported_in_usd`.
- **MSD: a printed subtotal tagged as a loan** at 2025-03-31 ('21,145 19,967 0.82' after the
  issuer's two rows). Rule `1849894/exclude_2025q1_lj_perimeter_subtotal`, one filing.
- **Rates:** `filed_rate_reading: all_in` for MSD, North Haven and Barings (the label or the
  arithmetic shows the rate fact is the whole coupon); loans with a PIK part published no rate
  before. Blue Owl Technology Income gets the reference-rate column and codes, and the
  cash-plus-PIK margin reading of the adviser's other fund.
- **Foreign principal:** `principal_usd_reference: fred_h10` for MSD, North Haven and Blue Owl
  Technology Income (principal had no dollar equivalent).

**Open on these five:** Barings 2023-06-30 (203.4M over; the same test leaves 6.9M unexplained, so
no rule); Barings, three or four loans a quarter whose PIK fact exceeds the rate fact and publish
no rate (the reason accepted for Ares Capital as DS-015, which has no check); Barings, the
excluded note rows now read as missing source rows (SRC_BDC01, 12 quarters; the DS-016 pattern);
Monroe, Evolve Biologics publishes a 16.00 spread as tagged; the 263 unread findings.

**Tests:** `test_source_encodings.py` 97 (one pinned set extended with its evidence),
`test_agent_promoted.py` 63. **Not run:** full suite, semantic diff, any 70-fund build.

### D-081 Largest-first, fourth batch: TPG Twin Brook, Antares Strategic Credit, Ares Core Infrastructure, Sixth Street Specialty Lending, Stepstone Private Credit (2026-10-10)

Sandboxes `l4a` to `l4c`, to 2026-03-31 (no later filings cached, none downloaded). Outstanding 456
to 380; 311 with the reasons the owner already accepted applied by their checks
(`large4_accepted_by_check.json`, 17 entries). The 311 are not read.

| Fund | Published against filed, as published | Now (l4c) |
|---|---|---|
| Stepstone (0001950803) | 1M to 119M off in eight quarters, both directions | 1M to 25M under in six quarters |
| Antares Strategic Credit (0001993402) | 2M to 19M under in seven quarters | 2M to 9.5M under in five |
| Sixth Street Specialty Lending (0001508655) | 1.0M over in one quarter | unchanged |
| TPG Twin Brook (0001913724), Ares Core Infrastructure (0002031750) | equal | equal |

**Fixes:**

- **Stepstone:** members ending ' One' / ' Two' are separate schedule rows (the Goldman Sachs
  pattern, D-063); 23 rows, 96.9M, were dropped as duplicates at 2025-09-30
  (`staging.distinct_member_suffix_re`). Two subtotal members of the private credit funds section
  published as positions at 2025-03-31 (32.4M each); `category_marker_re` extended.
- **Antares:** dollar values tagged with the loan's currency and converted twice
  (`foreign_unit_values`); `filed_rate_reading: all_in` (label: 'Interest Rate 9.40% (Incl. 3.13%
  PIK)'); `principal_usd_reference`.
- **TPG Twin Brook, Sixth Street Specialty Lending:** `filed_rate_reading: all_in`,
  `principal_usd_reference`.
- **Sixth Street Specialty Lending, issuer names:** 1,077 of 2,573 rows kept the schedule heading
  on the issuer name. Its own headings and instrument markers are now in its leaf guard; 384 rows
  were left after the first pass and a second pass (instrument markers) is applied but not yet
  rebuilt. Correction to D-077: the leaf-guard prefix of 0001925309 does not strip this fund's
  rows; each fund's prefix is applied to its own rows only.

**Open:** Antares, the tagged rows sum 2M to 9.5M below the filed figure (at 2026-03-31 all 1,392
tagged rows are published; the rest is printed and not tagged, or not in the schedule);
Stepstone, six quarters short, cause not found; the 311 unread findings.

**Tests:** wrapper, encoding and staging files pass. **Not run:** full suite, semantic diff,
any 70-fund build.

### D-082 Largest-first, fifth batch: KKR FS Income Trust, Goldman Sachs BDC, T. Rowe Price OHA, MidCap Financial, Stone Point Credit (2026-10-10)

Sandboxes `l5a`, `l5b`, to 2026-03-31. Outstanding 707 to 645; 555 with the reasons the owner
already accepted applied by their checks (`large5_accepted_by_check.json`, 14 entries). Not read
beyond totals.

| Fund | Published against filed, as published | Now (l5b) |
|---|---|---|
| KKR FS Income Trust (0001930679) | 13M to 571M over in all twelve quarters | unchanged (owner decision, below) |
| Goldman Sachs BDC (0001572694) | 46M to 135M over in six quarters, up to 15M under in others | 0.6M to 20M under in eleven, 16.4M over in one |
| MidCap Financial (0001278752) | 9M to 67M over in nine quarters | within 0.5M in eight; 5.2M and 17.9M over, 3.6M and 12.5M under in four |
| T. Rowe Price OHA (0001901164) | 2M to 19M off in seven quarters | equal in all |
| Stone Point Credit (0001825384) | 10.6M under in one quarter | unchanged |

**FOR THE OWNER: KKR FS Income Trust prints its loans gross of undrawn commitments.** The schedule
lists each loan at its full amount and then subtracts section lines: at 2026-03-31
'Total Senior Secured Loans - First Lien 2,415,774 2,396,109; Unfunded Loan Commitments (430,150)
(430,150); Net Senior Secured Loans - First Lien 1,985,624 1,965,959' and 'Total Asset Based
Finance 834,553 851,164; Unfunded Commitments (140,884) (140,884)'. The published rows are what
the filer tags, and their sum is 571.0M (430.150 + 140.884) above 'TOTAL INVESTMENTS 2,678,325'.
The two offset lines are tagged (InvestmentOwnedAtFairValue -430,150 on context c-509). Nothing
is changed here: publishing an offset row, or netting each loan, changes what a row means and is
the owner's call. KKR FS Income Trust Select (0001975736) is the same adviser and is likely the
same; not checked.

**Fixes:**

- **Goldman Sachs BDC:** from the 10-K for 2023-12-31 the equity and unsecured sections are filed
  under headings the wrapper did not know ('Investment Equity Securities', 'Investment Unsecured
  Debt', 'Investment Common Stock', ...), so their section subtotals were published as positions
  (136.1M at 2023-12-31). Prefix rules added and 'Total <section>' members read as subtotals.
- **T. Rowe Price OHA:** dollar values tagged with a foreign unit and converted twice
  (`foreign_unit_values`).
- **MidCap Financial:** members made of the industry and a group name alone ('Business Services
  Escalent', 9,381, beside the group's one loan at 9,381) are group subtotals; rule
  `1278752/exclude_group_name_subtotal_rows`.

**Open:** Goldman Sachs BDC is now short of its filed total in most quarters (with the subtotals
gone, positions missing elsewhere show); MidCap's four quarters; Stone Point 2025-12-31; the 555
unread findings.

### D-083 Largest-first, sixth batch: Diameter Credit, Carlyle Credit Solutions, Fidelity Private Credit Fund, Trinity Capital, Golub Capital BDC 4 (2026-10-10)

Sandboxes `l6a`, `l6b`, to 2026-03-31. Outstanding 423 to 366; 296 with the reasons the owner
already accepted applied by their checks (`large6_accepted_by_check.json`). Not read beyond totals.

**Fixes (settings only):** `filed_rate_reading: all_in` for Diameter ('Interest Rate 9.42% (2.75
PIK) ... Spread 5.75%'), Fidelity ('SOFR + 7.00% (0.50% PIK) Interest Rate 10.79%') and Carlyle;
`principal_usd_reference` for Carlyle; Golub Capital BDC 4 gets the adviser's rate reading,
reference-rate column and codes from 0001930087 (same layout and legend, read on its 10-Q for
2025-12-31), and `page_labelled_contexts` (63 rows sit on a group context; applied, not rebuilt).

**FOR THE OWNER: Fidelity Private Credit Fund's mutual funds.** The fund holds 'Fidelity Floating
Rate Central Fund' and 'Fidelity High Income Central Fund' (48.0M at 2024-12-31, 88.1M at
2025-06-30) in a 'Fixed Income Mutual Funds' section that is inside its filed investments total.
Its wrapper names them as not private-market, so they are left out and published sits 13M to
208M under the filed total in nine quarters. Leaving them out is a deliberate earlier choice;
whether they are published under a non-private class (as cash rows are since D-070) is the
owner's call.

**Open:** Carlyle 2024-12-31, 62.5M under: every tagged row is published (176 rows, 1,888.8M), so
the missing part is printed and not tagged, or tagged without an identifier; Trinity, up to 7.9M
off in seven quarters, and no rate published for its loans (the rate is in the label text only);
Golub Capital BDC 4, 10M under in two quarters until the page-labelled reading is rebuilt.

### D-084 Largest-first, seventh batch: Nuveen Churchill PCAP, BlackRock Private Credit, HPS Corporate Capital Solutions, T Series BDC, New Mountain Guardian IV (2026-10-10)

Sandboxes `l7a`, `l7b`, to 2026-03-31. Outstanding 347 to 250; 150 with the reasons the owner
already accepted applied by their checks (`large7_accepted_by_check.json`, 19 entries). Golub
Capital BDC 4, re-run in `l7a` with the page-labelled reading of D-083, now equals its filed total
in every quarter (57 outstanding to 32).

**Fixes (settings only):** `filed_rate_reading: all_in` for T Series ('S+ 5.00% (incl. 1.75% PIK)
Interest Rate 8.67%'), Nuveen Churchill, New Mountain Guardian IV and HPS Corporate Capital
Solutions (rate fact = reference rate + cash spread + PIK in each); `principal_usd_reference` for
T Series and HPS Corporate Capital Solutions; `foreign_unit_values` for T Series (Excelitas, par
EUR 6,487, value 7,581 published as 8,897).

**Open:** BlackRock Private Credit, loans with a PIK part publish the cash margin plus the PIK
margin as their rate (5.76 where the label says 'Total Coupon 9.42%'): its rate fact holds the
cash margin, unlike BlackRock Direct Lending's; T Series 14M to 20M over in two quarters and 2M in
two; Nuveen Churchill 5M to 16M under in three 2023 quarters (every tagged row is published);
HPS Corporate Capital Solutions 2M to 5M over in four quarters; the 150 unread findings.

### D-085 Largest-first, eighth batch: New Mountain Private Credit, Blackstone Private Real Estate Credit, AB Private Credit Investors, KKR FS Income Trust Select, Bain Capital Private Credit (2026-10-10)

Sandboxes `l8a`, `l8b`, to 2026-03-31. Outstanding 392 to 357; 301 with the reasons the owner
already accepted applied by their checks (`large8_accepted_by_check.json`, 12 entries).

**Fixes (settings only):** `filed_rate_reading: all_in` for AB Private Credit Investors ('9.46% (S +
3.00%; 1.00% Floor; 2.75% PIK)'), Bain Capital Private Credit ('7.50% (8.00% PIK) Interest Rate
15.50%') and New Mountain Private Credit; `principal_usd_reference` for Bain and KKR FS Income
Trust Select.

**FOR THE OWNER:** KKR FS Income Trust Select (0001975736) publishes 2.5M to 316M above its filed
total in eight quarters, growing with the fund: the same gross-of-undrawn-commitments schedule as
KKR FS Income Trust (D-082). Not changed.

**Open:** Bain, 33.5M and 41.5M under at 2025-09-30 and 2025-12-31: about eighteen rows of close to
5M each share the identifier of a larger row of the fund and are dropped as duplicates or never
published; whether they are the fund's own second tranche or the loans of its senior loan
programme was not read. Bain also has dollar values tagged with a foreign unit (six rows, 9.7M)
not yet set. New Mountain Private Credit, 36.9M over at 2024-12-31, not read. The 301 unread
findings.

### D-086 Largest-first, ninth batch: APS BDC, Jefferies Credit Partners, Antares Private Credit, Fortress Private Lending, Fidelity Private Credit Co (2026-10-10)

Sandboxes `l9a`, `l9b`, to 2026-03-31. Outstanding 254 to 211; 162 with the reasons the owner
already accepted applied by their checks (`large9_accepted_by_check.json`, 14 entries).

**Fixes:** `filed_rate_reading: all_in` for Fidelity Private Credit Co and Antares Private Credit
(labels state the rate including PIK); `principal_usd_reference` for Antares Private Credit;
`foreign_unit_values` for Jefferies and Fortress (Fortress is now equal to its filed total in
every quarter); Antares Private Credit's investments figure at 2025-03-31 supplied from the page
(company facts hold two values for the date and the smaller, 39.5M, was taken; the schedule
prints 1,103,954).

**Open:** Fidelity Private Credit Co, 9M to 67M under in five quarters: the same excluded Fidelity
mutual funds as the Fidelity Private Credit Fund (owner question of D-083); Jefferies, 0.5M to
1.6M under in seven quarters; the 162 unread findings.

### D-087 Largest-first, tenth batch: VISTA Credit Strategic Lending, 26North BDC, Goldman Sachs Private Middle Market Credit II, Crescent Capital BDC, Apollo Origination II (Levered) (2026-10-10)

Sandboxes `l10a`, `l10b`, to 2026-03-31. Outstanding 297 to 251; 166 with the reasons the owner
already accepted applied by their checks (`large10_accepted_by_check.json`, 18 entries). Published
equals filed in every quarter for four of the five; Crescent Capital BDC is 1M to 31M off in five.

**Fixes (settings only):** `filed_rate_reading: all_in` for Crescent ('S + 250 (plus 400 PIK)
Interest Rate 10.27%'), Goldman Sachs Private Middle Market Credit II, VISTA ('SOFR + 9.00% (9.00%
PIK) Interest Rate 12.83%') and 26North ('SOFR + 5.550 (Incl. 2.925% PIK)|9.277%'); Apollo
Origination II (Levered) gets the rate, margin, currency and reference-rate settings of Apollo
Debt Solutions (same layout: 'S+275 Cash plus 2.75% PIK').

**Open:** Crescent 2023-12-31 30.8M under and four smaller differences, not read; the 166 unread
findings.

### D-088 Largest-first, eleventh batch: Overland Advantage, NMF SLF I, Lord Abbett Private Credit, TCW Direct Lending VIII, AGL Private Credit Income (2026-10-10)

Sandbox `l11a`, to 2026-03-31. 376 outstanding as built; 327 with the reasons the owner already
accepted applied by their checks. `filed_rate_reading: all_in` set for NMF SLF I and TCW Direct
Lending VIII ('12.17% inc PIK (SOFR + 8.50%, 2.00% Floor, 1.00% PIK)'); both are re-run with the
twelfth batch.

**Open, real and large:**

- **Lord Abbett Private Credit (0002008748): 48M to 199M under its filed total in seven quarters.**
  The schedule names each issuer's main term loan by the issuer alone ('Accession Risk Management
  Group, Inc 3M S + 4.75% 9.05 % 11/1/2029 17,064 17,003 17,021') and its other tranches with a
  bracket ('... (Delayed Draw Term)'). At 2025-03-31 ten such main loans, 176.1M, have a tagged
  row and no published row; thirteen others are published. Where they are dropped was not found.
- **Overland Advantage (0001965934): 91M to 215M under in five quarters.** Every tagged row is
  published (71 rows, 1,151.0M at 2025-06-30, against a filed 1,366.1M). The missing part is not
  among the tagged position rows; not read on the page.
- NMF SLF I, 3M to 16M off in four quarters; TCW Direct Lending VIII has no filed investments
  figure in three 2023 quarters.

### D-089 Largest-first, twelfth batch: Silver Point Specialty Lending, TCW Direct Lending VII, MidCap Apollo Institutional, Phillip Street BDC, Crescent Private Credit Income (2026-10-10)

Sandbox `l12a`, to 2026-03-31, first build only (MidCap Apollo Institutional already carries the
Apollo settings of D-088). 631 outstanding for the five; 562 with the reasons the owner already
accepted applied by their checks (`large12_accepted_by_check.json`). NMF SLF I and TCW Direct
Lending VIII, re-run here with their rate reading: 99 to 86 and 97 to 79.

Totals, not read further: Silver Point within 1.5M; Phillip Street and Crescent Private Credit
Income within 2M except Crescent's two latest quarters (4.3M and 7.7M over). **TCW Direct Lending
VII has no usable filed investments figure** in nine quarters and two that are far below the
schedule (847.2M against 1,061.8M published at 2024-12-31; 657.3M against 1,013.2M at 2026-03-31);
its printed totals were not read. The fund-level figures need supplying from the page as for SCP
(D-078) and TCW Star (D-079), which belongs to the same adviser family.

Addendum to D-088 (Lord Abbett, lead for the fix): the parsed file holds the main loans
('Accession Risk Management Group Inc', 17,021 thousand, context c92 at 2025-03-31); they are lost
in staging. The wrapper declares prefix rules ('First Lien Secured Debt', 'Total ...') that only
its subtotal members use, and for a fund with prefix rules staging treats a row that has no
declared prefix and no instrument word, and whose name starts other rows' names, as a heading
(`pipeline/staging_bdc.py`, the prefix-rules block near line 840). The likely fix is to restate
this wrapper as a flat schedule (`dispatch.flat_schedule`, as for HPS) with the subtotal members
as aggregate markers. Not done.

### D-090 Largest-first, thirteenth batch, and where the cohort stands (2026-10-10)

Sandbox `l13a`, first build only: Varagon, Apollo Origination II (UL), Commonwealth Credit
Partners, Senior Credit Investments, TCW Direct Lending, Silver Capital Holdings, Manulife Private
Credit. 644 outstanding; 564 with the reasons the owner already accepted applied by their checks
(`large13_accepted_by_check.json`). Totals, not read further: Manulife 12M to 92M over in seven
quarters and 24M under in one; TCW Direct Lending has no usable filed investments figure;
Commonwealth 10M to 12M over in four quarters; Varagon up to 6M under in eight.

**Every fund of the 77-CIK manifest has now had a first sandbox pass.** Outstanding findings after
the check-accepted entries, by batch (sandbox of record):

| Batch | Funds | Outstanding | Read |
|---|---|---|---|
| First five (`final5`) | 5 | 0 | all |
| Next five (`n5j`, D-077) | 5 | 82 | all; 34 proposals await the owner |
| Largest-first 3 to 13 (`l3d` to `l13a`) | 57 | 3,624 | totals only |
| Smallest-first 1 and 2 (`s1c`, `s2a`; parked) | 10 | 620 | totals only |

The counts are sandbox ledgers to 2026-03-31 (2026-06-30 for the first ten). "Read" means read
against the filing. A fund whose published total equals its filed total can still carry wrong
rates, classes or names; the unread findings are where those would show.

## 2026-10-10 (later): owner rulings; reading every fund against its filings

Owner, verbatim, answering D-090's three questions: "1. net each loan 2. yes 3. explain the pik only
loans with spread issue" and "i want the same attention given to the largest first batches than to
the first 10. read against filings."

### D-091 KKR FS Income Trust and KKR FS Income Trust Select: undrawn commitment rows are published net

- **Decision (owner: "net each loan").** New wrapper setting `source_encodings.unfunded_rows:
  ["net_of_tagged_commitment"]`, set for 0001930679 and 0001975736. Module
  `pipeline/unfunded_commitments.py`, called by the extractor and by source reconciliation; the
  re-verifier replays the event `net_of_commitment:<amount>` recorded in `src_facts`.
- **Mechanism.** The schedule lists an undrawn commitment as its own row at the committed amount
  ("Sotheby's, Revolver (i) ... 31,849 31,849 31,849", footnote (i) "Security is an unfunded
  commitment") and subtracts "Unfunded Loan Commitments (430,150) (430,150)" per section. The same
  filing tags every commitment in its commitments note
  (`InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount` on the investment's member). A
  schedule row of the same date whose name starts with the commitment's name and whose cost equals
  the tagged amount is that commitment's row: its cost and fair value are reduced by the amount
  (cost 0, fair value = the mark, e.g. AGS Health 1,628 - 1,679 = -51); principal keeps the
  committed amount.
- **Measured** (`python scripts/v05_evidence/commitment_match.py 1930679`): 0001930679 matches every
  tagged commitment in ten of twelve filings (165 of 165, 570,751K, at 2026-03-31; 3 unmatched in
  the other two); 0001975736 matches all in six of nine (6 unmatched in three).
- **Two older rules removed** (`git rm`): `1930679/exclude_exact_par_commitment_rows_2025h2` and
  `1975736/exclude_2025_12_unfunded_commitment_rows`. They dropped "exact par" rows by value in
  listed quarters; with the netting they removed funded rows too (first run `k1a`: 220M to 287M
  under in three quarters).
- **Result, sandbox `k1b`.** Published against filed: 0001930679 was 13M to 571M over in all twelve
  quarters, now equal in three and 1.5M to 14.1M over in nine; 0001975736 was 2.5M to 316M over in
  eight, now equal in four and 1.7M to 9.7M over in five. The remainder is not read (unmatched
  commitments, or a row the note does not list: at 2026-03-31 the offsets print 571,034 and the
  note 570,751).
- **Both funds are held back from the public 70** (manifest note: over-inclusion 1.15x and 1.18x).
  Whether they now pass admission was not tested.
- **Also fixed:** the provenance summary failed when no fund of a run is in the 70-fund cohort
  list (`pipeline/provenance_reverify.py`, typed empty frame). The re-verifier does not cover the
  seven held-back funds.
- Tests: `tests/test_unfunded_commitments.py` (8). Re-run: `commitment_match.py <cik>`.

### D-092 The PIK-only-with-spread question, explained (nothing changed)

Two different cases publish no `interest_rate` today:

| Case | Printed | Tagged | Count in the first five (rows, all quarters) |
|---|---|---|---|
| Whole coupon is PIK | Ares Strategic Income, 22 HoldCo: "11.55 % PIK SONIA (S) 7.50 %" | PIK 11.55, spread 7.50, no plain rate | Ares 302, BCRED 140 (e.g. CB Nike 11.02 / 7.35) |
| PIK is part of the margin | Blue Owl, Deerfield Dakota: spread 5.75, PIK 2.75, no coupon printed | spread, PIK margin | Blue Owl 491, Apollo 199, HPS 88 |

`pik_only_tag_reading: coupon` fills the rate from the PIK tag only when no spread is tagged
(D-018). Recommendation put to the owner: fill the first case (PIK figure above the spread) and
leave the second empty. Not done: it changes first-five rows.

### D-093 What no finding reports: field defects measured across all 77 funds

`python scripts/v05_evidence/cohort_field_health.py` (output kept in
`scratch/2026-10-10_read/cohort_field_health.txt`; each fund from its latest sandbox). Published
loan rows:

- **Reference rate guessed from the report date** (`reference_rate_source` = inferred): above 60 pct
  of loan rows in 31 funds, among them Ares Capital 75, BCRED 79, HPS 62, Blue Owl 66. The guess is
  LIBOR before July 2023 and SOFR after, so it is wrong for SOFR loans in early 2023 and for every
  EURIBOR, SONIA, CORRA or BBSY loan. Read on the page so far: Barings 2023-06-30, all 376 rows
  LIBOR, page prints SOFR 162, EURIBOR 83, LIBOR 79, SONIA 29, BBSY 18; North Haven 348 loans
  (2,127.6M) LIBOR at 2023-03-31 where the page mixes "S +" and "L +"; Monroe 275 loans (1,440M).
  A fund whose wrapper names its printed column (`reference_rate_columns`) has the printed code
  replace the guess; from 2025 filers also tag the benchmark per row
  (`InvestmentVariableInterestRateTypeExtensibleEnumeration`), which nothing reads into holdings.
- **No interest rate on 90 pct or more of loans:** KKR FS Income Trust Select, Senior Credit
  Investments, Jefferies, Overland, the three Apollo-layout funds, MidCap Financial, both Blue Owl
  funds, Stellus, Stepstone at the latest date. Some are as filed (Blue Owl prints no all-in rate);
  most are not read.
- **Issuer not split from the label** (distinct issuers above 90 pct of rows): every quarter for
  BCRED, HPS, Stone Point, T. Rowe Price OHA, Monroe, Manulife, Diameter, Lord Abbett, HPS Corporate
  Capital Solutions, SCP, Blackstone Private Real Estate Credit; most quarters for Barings, Blue Owl
  (both), Golub Capital BDC 4, T Series, North Haven, NexPoint, Carlyle. The measure is a screen:
  a fund with one tranche per borrower would also trip it. BCRED and HPS need a look.
- **No maturity:** Blue Owl 41 to 46 pct at the latest date (both funds), Antares Strategic 28,
  Senior Credit Investments 25, Jefferies 17, APS 100.

None of this is counted in "outstanding findings". It is the measured form of "all findings
cleared is not data correct".

### D-094 Reading against filings: first fixes built (Barings, Lord Abbett, Overland), and one that failed its first form

Readings are kept in `docs/investigations/v05_readings/<cik>.md`; the list of real errors and their
state is `docs/investigations/v05_reading_backlog.md`. 21 funds read so far.

- **Barings (sandbox `b1a`).** New wrapper setting `source_encodings.schedule_row_tags:
  ["cost_or_percent_unrounded"]` (`pipeline/schedule_row_tags.py`, extractor and source
  reconciliation): a context is a position only if it carries a cost tag or a percent-of-net-assets
  tag and no value fact rounded more coarsely than the thousand. It replaces four row-exclusion
  rules (moved to `1859919/_pulled_superseded_by_schedule_row_tags_2026-10-10/`). Result: 2023-06-30
  from 203.4M over to 6.9M under (two real rows still missing: CPCF schedule row c-838 4,534 and
  Finexvet c-329 2,388); the other twelve quarters equal filed; cost at 2026-03-31 equals the
  printed 5,231,456 (was 31.1M over). Staging block `hierarchy_extract` splits the older
  'issuer, [industry,] instrument' member: 288 issuers for 494 rows at 2023-06-30 (was 491 for
  503). `pik_only_tag_reading: coupon`; `reference_rate_columns: ["Interest"]` (at 2023-06-30
  LIBOR falls from 376 rows to 193; the page prints 79, so the printed read is still partial).
  Outstanding findings for the fund 107 to 45. Tests `tests/test_schedule_row_tags.py` (4).
- **Lord Abbett (sandbox `b2a`).** New wrapper key `dispatch.bare_entity_rows: "positions"`
  (`pipeline/staging_bdc.py`): the bare-entity subtotal filter of prefix-rule filers (condition 2d)
  does not apply. Published now equals filed in all seven quarters (was 48M to 199M under; 32 rows,
  662.1M). One context named through `context_identifiers` (Arkas Bidco equity). Open: the
  restored joint-venture interest and equity rows class as loans; percent of net assets 100 times
  too small at 2025-06-30; issuer names.
- **Overland (sandbox `b2a`).** The Treasury bill the filer tags with no identifier in three
  filings is named through `context_identifiers`; it now publishes, as a cash-class row. The filer
  counts it inside 'Total Investments' (2025-06-30: 1,150,961 + 215,151 = 1,366,112), so published
  excluding cash still reads 91M to 215M under. FOR THE OWNER: cash class (as now) or an investment
  row. Open: money funds from 2025-06-30, Summit Materials 4.0M at 2024-06-30.
- **Issuer row numbers (BCRED, HPS, North Haven, Monroe): first form rejected.** New key
  `dispatch.issuer_name_strip_re` ('\s+\d{1,2}$'). Applied in staging (sandbox `b2a`) it made twin
  rows collapse and unhooked rules that name a row: BCRED 48M under in nine quarters, HPS up to
  70M under, North Haven 22M over in two. It now runs at the end of the unified build, after the
  duplicate filters, rules and corrections; rebuilt as `c1a` (result in the next entry). In `b2a`
  the names themselves came out right: BCRED 833 issuers for 1,288 rows at 2026-03-31 (was 1,257),
  HPS 403 for 812 (was 794).

### D-095 Reading against filings: second round of builds (sandboxes `c1a`, `c2a`); 31 funds read

- **Issuer row numbers, second form: holds.** `dispatch.issuer_name_strip_re` now runs at the end
  of the unified build (`pipeline/unified_holdings.py`). Sandbox `c1a`: BCRED, HPS, North Haven,
  Monroe and MSD equal filed in every quarter; issuers at 2026-03-31: BCRED 833 for 1,288 rows
  (was 1,257), HPS 404 for 813 (was 794), North Haven 324 for 680, Monroe 705 for 923. This changes
  first-five rows (issuer_name only); position ids and the first five's findings were not compared
  with `final5` yet.
- **Fidelity Private Credit Co and Fund (c1a).** Shared double-prefix regex widened to the comma,
  em-dash and truncated forms (only these two filers use them; MSD, the third filer declaring the
  prefix, is unchanged in totals); 72 industry labels, leaf guard, twin suffix and dispatch
  patterns from the reader's tested proposal (`v05_readings/proposals/`); rule
  `exclude_mutual_fund_section_rows` for both. Co: equal to filed in all quarters but 2023-06-30
  (1.4M under); it was 9M to 67M off in five. Fund: names repaired (12 of 345 still carry a heading
  at 2026-03-31, was 110); still under in nine quarters: the central funds did not publish because
  `cash_identifiers` is matched after the prefix is stripped (stripped forms added, rebuilt in
  `d1a`), and 104.9M at 2025-06-30 is twelve positions whose fair value sits on a context dated
  2025-03-31 (no setting covers a value on another date's context of the same member). Not
  applied from the proposal: `leaf_guard.allow_dash` and the markerless equity path (new code).
- **Settings from the readings (c2a).** Carlyle: 23 structured-credit contexts re-dated
  (`misdated_contexts`), now equal to filed in every quarter (was 62.5M under at 2024-12-31).
  Goldman Sachs BDC: `foreign_unit_values`, `filed_rate_reading: all_in`, `principal_usd_reference`,
  `investments_total_excludes`, twin suffix: off in three quarters by 0.9M to 4.1M (was eleven
  quarters, up to 20M); loans with no rate 34 to 41 pct down to 24 to 31. MidCap Financial:
  `foreign_unit_values`: two quarters left (the two rows the filing tags wrongly). T. Rowe Price
  OHA: `filed_rate_reading: all_in`: PIK-part loans with no rate 50 to 0 at the latest date.
- **Printed reference-rate column: header match.** A named header did not match a printed header
  ending in a footnote mark ('Reference Rate and Spread (5)'), so the setting did nothing for
  T. Rowe Price OHA and Ares Core in `c2a`. `pipeline/bdc_xbrl_html_bridge.py::_named_header` now
  drops trailing footnote marks before comparing. Columns named for nine more funds; HPS Corporate
  Capital Solutions takes its sister's code table, whose change dates were NOT read on its own
  pages. Rebuilding as `d1a`, `d2a`.
- **Two promoted corrections pulled** (moved to `_pulled_wrong_remap_2026-10-10/`): Bain
  `column_remap` moved cost into principal on 310 rows (cost 122.3M wrong at 2025-12-31; the filing
  tags all three columns correctly, Caliber "2,856 2,856 2,863"); Stepstone `column_remap` erased
  PIK on 40 rows at 2025-12-31 (Pave America printed "8.92 % / 2.88 %").
- **Corrections to earlier statements of mine.** Golub Capital BDC 4 does not tie in every quarter
  (D-084 read a build made before its settings applied); Bain's 'dropped twin rows' (D-085) are its
  senior loan programme's loans, rightly unpublished; BlackRock Direct Lending's PIK-loan rates are
  wrong in the same way as BlackRock Private Credit's (D-084 said they differed); Nuveen
  Churchill's rate tag is the cash figure, so D-084's `all_in` was wrong (now `cash_leg`).
- **Shared defects with no fix yet:** a position's value filed on a prior date's context (Fidelity
  Fund, Bain, Trinity, AB, Goldman Sachs BDC); values filed without the thousands scale (Bain,
  Stone Point, Stepstone); rows printed with a dash for fair value dropped, which understates cost
  (Goldman Sachs BDC up to 132.6M, Trinity, Diameter, AB, MidCap, Sixth Street); coupon, cash
  margin and PIK margin tagged apart (both BlackRock funds, TPG Twin Brook, Stepstone); the
  per-row benchmark tag filed from 2025 read by nothing; net investment income holding total
  income or a per-share figure (Goldman Sachs BDC, AB, Monroe, Blackstone Real Estate Credit).

### D-096 Third round (sandboxes `d1a`, `d2a`, `e1a`); the promoted column-remap corrections; 40 funds read

- **Results.** HPS Corporate Capital Solutions equal to filed in all eight quarters (roll-forward
  rows removed by `schedule_row_tags`; issuer row marks stripped). T Series equal in twelve of
  thirteen (1.7M under at 2024-12-31). Fidelity Private Credit Fund: central funds now publish as
  cash-class rows; nine of thirteen quarters tie; left are 104.9M at 2025-06-30 (values on a
  prior-dated context) and 60.6M over at 2025-03-31 (two subtotals tagged on position labels), both
  filing errors, and two 2023 quarters not read. Crescent Capital BDC: six contexts re-dated; left
  are the Ancora issuer subtotal (6.3M, 6.4M over) and one untagged cell (1.2M). Bain: six
  contexts re-dated; left are 33.5M (two rows filed without the thousands scale) and 11.2M (two
  rows filed in whole dollars). Jefferies: commitment-table contexts removed
  (`schedule_row_tags: not_commitment_only`), equal in nine of ten quarters (1.2M over at
  2025-03-31, two subtotals). Antares Private Credit equal in all. Antares Strategic: commitment
  rows removed by rule `exclude_commitment_table_rows`; now 3.3M to 4.2M OVER in three quarters,
  which is the add rule `add_blackrock_short_term_investment_2025` (a plug sized to the old gap):
  to retire once the tagged money-market row is published. New Mountain Guardian IV equal in all
  (`quantity_or_percent` removes one note aggregate).
- **A test that failed on one fund.** `quantity_or_percent` on New Mountain Private Credit removed
  a real row at 2025-12-31 (Bonterra LLC, 7,308): the filer tags that loan's values on c-263 and
  its principal and rates on c-262. Setting withdrawn for that fund; the one note aggregate is
  excluded by a rule pinned to its filing and context
  (`2037804/exclude_2024q4_nonaccrual_note_aggregate`).
- **Printed reference rate.** With the header fix, T. Rowe Price OHA at 2023-06-30 publishes SOFR
  113, LIBOR 36, CDOR 4, EURIBOR 1, the page's own counts (was 154 LIBOR). `reference_rate_source`
  stays 'inferred' where the printed code agrees with the guess, so the screen in D-093 overstates
  what is still wrong for a fund whose column is named.
- **New setting** `source_encodings.rate_tag_reading: ["coupon_with_margins"]`
  (`pipeline/rate_tag_reading.py`, extractor and source reconciliation): the plain rate tag is the
  coupon and the paid-in-cash tag the cash margin. Set for BlackRock Private Credit, BlackRock
  Direct Lending and TPG Twin Brook; building as `f1a`. Tests `tests/test_rate_tag_reading.py` (5).
- **Promoted `column_remap` corrections (agent_b2_corrections), all scoped to 2025-12-31, the
  signed-off quarter.** Ten existed. Read so far: Bain (cost moved into principal, 310 rows, cost
  122.3M wrong) and Stepstone (PIK erased, 40 rows): pulled (D-095). Golub Capital BDC 4 (spread
  moved to PIK on every loan: 543 loans, 2.34B, publish no spread and a rate of the coupon plus the
  spread, Denali 14.73 for a printed 9.23; confidence recorded 0.62): to pull. Crescent Capital BDC
  (share counts moved into principal: 75 rows with a share count at 2025-09-30, none at
  2025-12-31): to pull. Senior Credit Investments (same remap, share counts 4 to 0): to pull.
  Audax, Silver Capital, TPG Twin Brook (confidence 0.42) and AGL (0.41) show no change in the
  counted fields; not read. These are in the published build.

### D-097 All 57 largest-first funds read; fourth round of builds (`f1a`, `g1a`, `h1a`)

- **Coverage.** A report exists for every fund of batches 3 to 13 (55 files in
  `docs/investigations/v05_readings/`; the two KKR funds were read by me, D-091). The ten parked
  small funds (D-078, D-079) are not read. No reader rebuilt anything; every proposed fix is
  untested until a sandbox shows it.
- **`f1a`.** `rate_tag_reading: coupon_with_margins`: BlackRock Private Credit and BlackRock Direct
  Lending PIK loans publish the printed coupon (IQN 9.45, cash margin 2.63, PIK 3.13; was 5.76);
  no PIK loan without a rate in either fund. TPG Twin Brook takes the setting; its rows were not
  re-read on the page. New Mountain Private Credit equal to filed in all quarters.
- **`g1a`.** Three `column_remap` corrections pulled (Golub Capital BDC 4, Crescent Capital BDC,
  Senior Credit Investments): Golub BDC 4 at 2025-12-31 back to 91 PIK loans and an average rate
  of 8.86 (was 543 and 13.32); Crescent share counts back (73 rows); Senior Credit 4 rows. A
  seventh, AGL's (moves the principal of its largest loan, 60.3M, into shares), pulled after its
  reading. Left unread: Audax, Silver Capital, TPG Twin Brook.
- **`h1a`.** Phillip Street (`foreign_unit_values`, `all_in`) and MidCap Apollo Institutional (plug
  rule `add_2026q1_seko_common_equity` pulled) equal to filed in all quarters. Crescent Private
  Credit Income: two quarters left (1.5M, 2.3M under; real rows dropped as duplicates). **Silver
  Point regressed**: with the value-matching dedup rules 01 and 02 pulled and
  `schedule_row_tags` set, published is 20.1M to 59.0M OVER in four quarters (category subtotals
  the old rules had been hiding). Rule `exclude_rows_without_a_leaf_marker` added (a schedule row
  names its acquisition or maturity date); rebuilt in `i1a`.
- **Applied for `i1a`, not yet checked:** TCW Direct Lending VII (`schedule_row_tags`,
  `filed_rate_reading: all_in`, `bare_entity_rows`), TCW Direct Lending VIII (`schedule_row_tags`),
  Varagon, Commonwealth, Silver Capital (`all_in`), Senior Credit (`not_commitment_only`,
  `foreign_unit_values`, `principal_usd_reference`; rule removing a real National Express row
  pulled).
- **Read and not yet acted on (largest):** Manulife's undrawn commitments are published gross
  (17.5M to 105.6M a quarter; tagged `us-gaap:OtherCommitment`, so `unfunded_rows` does not fire)
  and a rule sets cost equal to fair value on all 1,707 rows; TCW Direct Lending publishes a
  Treasury bill and affiliate-note rows as positions (323.1M over at 2026-03-31, 288.3M at
  2025-06-30) through five rules; the printed investments totals of TCW Direct Lending (13
  quarters) and TCW Direct Lending VIII (three 2023 quarters) are in their reports, to be supplied
  as the filed figure; TCW Direct Lending VII and VIII publish paid-in capital as net assets; three
  TCW VIII loans (92.4M, 2023-09-30) carry no tag at all.

### D-098 Fifth build (`i1a`) and state at the end of the day

- **`i1a`.** Silver Point equal to filed in all twelve quarters with rule
  `exclude_rows_without_a_leaf_marker` (the regression of D-097 is gone; the two value-matching
  dedup rules stay pulled). TCW Direct Lending VII: affiliate roll-forward rows removed; the two
  quarters that have a filed figure now tie (2024-12-31, 2026-03-31; published had been 215M and
  356M above them); eight quarters still have no filed figure in the fund-level data (printed
  totals are in its report, not yet supplied); loans with no rate 73 to 87 pct down to 0 to 1.
  Senior Credit: one quarter left (7.1M under, two rows filed without the thousands scale); loans
  with no maturity 25 pct to 0. Varagon: PIK loans with no rate 62 to 0; totals unchanged (rows
  without the thousands scale, twins). Commonwealth: PIK loans with no rate 15 to 0; the Kent
  Water Sports note rows (9.6M to 11.5M over in four quarters) still published. AGL correction
  pulled.
- **Tests:** 1,047 pass across the fourteen test files of the modules touched since ae19926
  (rate tags, schedule-row tags, unfunded commitments, encodings, wrapper, oracle, page contexts,
  staging refactor, signatures, promoted rules, re-verifier, fund income, derivatives, fund-level
  wrapper). **Not run:** the full suite, the semantic diff, any 70-fund build, re-attestation.
  The builds above are per-fund sandboxes of different dates; no single build holds all 77 funds
  with today's settings.

## 2026-10-11: funds one at a time, largest first (owner: "keep processing funds, one at a time, from largest to smallest")

Order: cohort by 2026-03-31 fair value. The first five are at 0; the next five wait on the owner's
view of 34 proposals; so the run starts at the eleventh fund. Per fund: apply the fixes its reading
(`v05_readings/<cik>.md`) calls for, each checked on the page first; build the fund alone; compare
every field with the previous sandbox; write proposals for what a reading explains
(`scripts/v05_evidence/make_fund_proposals.py`, spec in `v05_readings/proposals/<cik>_reading.json`,
output in `data/overrides/finding_dispositions_proposed/fund_<cik>.json`, which the ledger does not
read). Nothing is published, pushed or accepted by me.

### D-099 MSD Investment Corp. 0001849894 (sandbox `m1a`, before `l3d`)

- **Reference rates read from the page.** `reference_rate_columns: ["Reference Rate and Spread"]`
  and codes S, L, E, SO=SONIA, SA=SARON, B=BBSW, C=CDOR, P=PRIME, from the schedule note of five
  filings (2023-03-31 to 2026-03-31). 65 rows change: SONIA 44 rows (1,291.6M), SARON 10 (788.3M),
  BBSW 4 (198.3M), CDOR 5 (404.2M) had been published SOFR or LIBOR. Two rows now differ from the
  member label and match the page: Boasso revolver 2024-03-31 'P + 5.75 %', Dellner 2024-06-30
  'L + 5.50 %'.
- **Issuer names.** `dispatch.issuer_name_strip_re` removes a trailing tranche phrase, ' One',
  ' EUR' / ' GBP' and the en-dash separator: 196 distinct names to 162, 107 rows, no other name
  touched (dry run `scratch/2026-10-11_msd/strip_dry_run.py`). The filer's own spellings
  ('Parfums Holding Co.' in four forms, 'USA Debusk / Debunk') stay.
- **Row corrections (17, `row_corrections.csv`, each line read on the page):** the 49.3M Accession
  Risk Management loan the filer tagged on a Titan Purchaser member (2024-12-31; issuer and
  description corrected, industry not correctable); six rows whose whole rate is tagged with the
  PIK concept while the page prints no PIK (Watchguard 74.0M, 7Ridge delayed draw, Legends x4):
  PIK withdrawn; Beacon delayed draw 2024-06-30 rate 13.94; Sky Merger delayed draw, eight
  quarters, cost 0 (page prints a dash; 5,000 had been a proxy). The reader's seventh PIK row,
  Ligado 2024-12-31, is NOT changed: the page prints '15.5 % PIK'.
- **Result.** Published equals filed in all 13 quarters, before and after. Ledger 58 outstanding
  to 42 (X07 gone). Field comparison: only the fields above changed, plus entity and industry
  labels on rows whose name changed (7 rows change GICS sub-industry).
- **Proposed, not accepted (38 findings, eight reasons):** B01 (the check counts text-only
  contexts; a rule problem), C04, A01, maturity_not_past (Ligado), PCT01, the excluded LJ Perimeter
  subtotal (2), one percent tag. **Left open (4):** F27 x3 and F16 x1, weak fund-level heuristics
  whose cause was not found.
- **Not done:** the Titan/Accession row keeps industry Automotive; warrant rows class as common
  equity; no check exists that would have caught the Accession mis-tag, the rate codes or the names.

### D-100 North Haven Private Income Fund 0001851322 (sandbox `n1b`, before `l3d`)

- **Names.** 2025-09-30 on: the label's word "Investment" is now optional and "Other Debt" /
  "First Debt" are instrument types, so 69 loans (778.3M at 2025-09-30) that had published the
  whole label as the issuer are split; the joint venture row is 'North Haven Keystone, LLC' in
  both quarters. To 2025-06-30: the row ordinal is stripped (354 names to 212 at 2023-03-31, 640
  to 325 at 2024-12-31). Left: two Spectrum Automotive rows at 2025-09-30 whose label has no
  instrument type (C206).
- **Classes (row corrections, 325 field values, quarters to 2025-06-30).** Preferred equity
  published as loans, 4 to 6 rows and 25.9M to 39.4M a quarter (FORTIS, Knockout, RSK, Revalize,
  Integrity Marketing, Verdantas): class corrected; at 2023-09-30 also five common equity rows,
  with the share count moved out of principal. FORTIS, Knockout, Integrity and Verdantas print a
  fixed rate in the reference column ('Preferred Equity 12.25 %'): rate published, spread
  withdrawn, coupon Fixed. **RSK and Revalize print 'S + 10.50 %' / 'S + 10.00 %': floating, the
  spread stays.** My first build had moved their spread into the rate as well; caught on the page
  and removed before the second build. TruGreen Limited Partnership (a first lien loan, 4.5M to
  4.8M) is a loan, not a fund.
- **Reference rates read from the page.** Column 'Reference Rate and Spread', codes S, L, E, P,
  F=FEDFUNDS, C=CORRA, SA=SONIA (legend read in all 13 filings). 659 rows change, mostly 2023-03-31
  and 2023-06-30 loans published LIBOR that print 'S +'; CORRA 13 rows, SONIA 6, PRIME 72. Where
  the page agrees with the date guess the source label still says 'inferred' (3,961 rows): the
  value is confirmed, the label is not updated (shared code, not changed).
- **A hierarchy-note line published as cash.** 'Investment measured at net asset value' (85.3M,
  99.2M; the Keystone stake again) is tagged on the cash axis, and shared code reads any cash-axis
  member as cash. Removed for this fund by rule `exclude_fair_value_hierarchy_nav_row` (all
  quarters). An aggregate marker did not reach it. Shared rule not changed: owner question whether
  a cash-axis member that names no cash should be read as cash for any fund.
- **Fund level.** Net assets 2023-09-30 corrected to 1,898,269,000 (page; the prior year-end had
  been taken) in a new fund-level wrapper. Side effect by design: the calculated percent of net
  assets is blank for that quarter (the corrected figure no longer equals the company-facts value).
- **Atlas Purchaser added row** now carries its accession and classes.
- **Result.** Published equals filed in all 13 quarters. Ledger 31 outstanding (the l3d count for
  this fund was not recorded separately); conservation and the 2023-09-30 net-asset group (8) are
  gone. Field comparison against `l3d`: only the fields above, plus entity and industry labels
  following the name change (936 rows change GICS sub-industry: labels are keyed on the issuer
  name; not checked against the printed industry heading).
- **Proposed, not accepted (23 findings).** Left open (8): year-end distribution per share holds
  the full-year figure (F16 x3, F33 x2; real, fund-level, shared code); non-accrual list not
  compared with the footnote; C103 2024-12-31 (an earlier reviewer called it a real error, the
  reading says undrawn lines); C206.
- **Not done:** the Keystone look-through rule stays pinned to two quarters (a format-only
  predicate also matched two real rows at 2025-09-30, so it was not generalised; the carry-over
  check will flag the next quarter); the tagged benchmark enumeration (2025-09-30 on) is not read;
  'P +' member labels are unreliable (Sonny's) and the page reading now overrides them; three
  non-accrual loans at 2025-06-30 print a rate the filer did not tag; year-end income is blank.

### D-101 Monroe Capital Income Plus 0001742313 (sandbox `mo1c`, before `l3d`)

- **Names.** `dispatch.issuer_name_strip_re` now removes ', Senior Secured Loans ...',
  ', Equity Securities ...', a tranche parenthetical and the row number: 3,536 distinct names to
  578 over 8,523 rows. New opt-in `dispatch.issuer_name_strip_to_instrument` (generic code, set
  for this fund only; `_strip_issuer_names` in `pipeline/unified_holdings.py`, six tests in
  `tests/test_issuer_name_strip.py`): the removed text becomes the instrument description where
  that was blank (6,598 rows, e.g. 'Senior Secured Loans (Delayed Draw) 1'). From 2025-12-31 the
  member already gives 'Senior Secured Loans' as the instrument, so there a tranche parenthetical
  is dropped from the name and kept only in the identifier.
- **A class regression found and fixed in the same run.** 113 rows of the Equity Securities
  section with no share-class word had category OTHER; 106 of them got their index class from a
  cache keyed on the old full name. Stripping the name lost the key (85 rows became UNCLASSIFIED,
  17 took the issuer's loan class, 80.0M). Now set by row correction (339 values): category
  EQUITY_COMMON, class COMMON_EQUITY. This also classes the seven rows (90.6M) that had been
  UNCLASSIFIED before. Quarter-pinned: a later quarter's rows of this kind will need the same.
- **Reference rates from the page.** Column 'Index'; codes SF, L, P, C=CDOR, CA=CORRA, SN=SONIA,
  BB=BBSW, EU=EURIBOR (legends of four filings). 575 rows change (2023 loans printed 'SF'
  published LIBOR; PRIME 87, SONIA 13, CDOR 12, CORRA 4, EURIBOR 3, BBSW 3).
- **PIK-only loans.** `pik_only_tag_reading: coupon`: a loan whose only rate tag is the PIK tag
  and that has no spread publishes that figure as its rate (Witkoff/Monroe 700 JV 'n/a n/a
  13.25 % PIK'). Loans with a PIK tag and no rate 299 to 204. The 204 left have a spread
  ('SF 8.76 % 12.47 % PIK'): the open owner question of D-092.
- **One row.** FLEET Response 2025-12-31 published 25.25 (a cash tag of 15.28 not on the page plus
  PIK 9.97). A correction to 9.97 was read as a cash rate and published 19.94, so the cash tag is
  withdrawn instead: the row now reads like its two sibling rows (PIK 9.97, spread 6.10, no rate).
- **Fund level.** Shares outstanding 2023-03-31 corrected to 83,765,000 (page; the prior year-end
  had been taken). F11, nav_identity and E04 cleared.
- **Result.** Published equals filed in all 13 quarters. Ledger 63 outstanding: 28 proposed (five
  reasons), 35 left open. Open and real: net investment income holds a per-share figure in four
  2022-2023 quarters and wrong year-end remainders (income_identity x5, F27 x7: fund-level
  extractor, shared code); X02 x5 (PIK with spread, D-092); the rest unread (C04 2023 share
  counts, PP03, eight provenance rows of no value, X05 Argano, C115 2023-03-31).
- **Side effects seen:** two warrant rows at 2024-09-30 lose a maturity (the expiry date) that had
  come from the page reading; ten zero-value twin rows now trip PP02 (proposed as a rule problem);
  entity and industry labels move with the names (814 rows change GICS sub-industry, not checked
  against the printed heading).
- **Not done:** warrants still class as common equity with the expiry in maturity; SingleStore
  equity commitment (9.3M) still a loan; three of the four exclusion rules stay pinned to one
  filing.

### D-102 Blue Owl Technology Income Corp. 0001869453 (sandbox `o1b`, before `l3d`)

- **Names.** To 2025-09-30 the issuer name was the whole member ('Certify, Inc., First lien senior
  secured loan'). `issuer_name_strip_re` cuts at the instrument words and
  `issuer_name_strip_to_instrument` keeps them as the instrument description: 900 distinct names to
  334 over 3,957 rows. One name left unsplit (a filer typo, 'Bracket Intermediate ... loanidCo LLC').
- **Rates** (the printed 'Interest' / 'Ref. Rate' column was named in an earlier round; this is the
  first single-fund build with it): 288 rows take the printed reference rate (2023 loans printed
  'S +' published LIBOR); Inovalon second lien 'S + 10.50 % PIK' publishes its margin; fixed
  coupons on XRL, Acrisure, Associations Finance and TK Operations publish as rates.
- **Row corrections (15 values, each read on the page).** OEConnection 17.1M loan tagged on a
  McQueen Bidco member (2025-12-31): issuer and spread 4.50. RealPage spread 3.00 (2025-03-31,
  2025-06-30) and Engage Debtco 5.90 with 2.40 PIK (2023-09-30): printed, not tagged. Kaseya and
  Associations 2024-03-31: spread and PIK tags swapped (89M), found by the printed-spread check.
  Blue Owl Credit SLF 2024-09-30 classed equity.
- **LLC interests as loans** (three rows, 25.0M, 2026-03-31): `equity_instrument_labels:
  ["LLC Interest"]`. Blue Owl Credit SLF then took a proxy share count from an earlier quarter
  (14,293 against a printed 16,161): corrected to the printed units.
- **Fund level.** Net assets 2023-03-31 1,149,711 and 2023-06-30 1,340,153, total assets
  2023-03-31 2,153,216 (pages; a later 10-Q had refiled the next year's balance on those dates).
  Calculated percent of net assets is blank for the two quarters (265 rows), by design.
- **Result.** Published equals filed in all 13 quarters. Ledger 35 outstanding to 6: X02 accepted
  by its check in four more quarters (D-073); 5 proposed (two reasons); 1 left open and real:
  fourth-quarter 2022 income is the year divided by four (fund-level extractor, shared code).
- **A defect the cleaner names exposed, not fixed.** The cost proxy takes the first fair value of
  a position's chain. With names split, an undrawn Packaging Coordinators delayed-draw line
  (fair value -0.3M) is chained to a different 5.0M loan of the same issuer and publishes a cost of
  4,994,000 in two quarters. 631 rows of this fund carry a proxy cost (14.5M in all; four are more
  than ten times their fair value). The proxy is shared code. Owner question: publish no cost
  where none is filed, instead of a proxy.
- **Not done:** LP interests class three ways; warrants class as common equity; Inovalon
  2023-03-31 keeps a date-guessed LIBOR; net assets of 2022-03-31 and 2022-06-30 (before the first
  schedule) hold the 2023 balances; NAV per share and shares outstanding are empty in every quarter.

### D-103 Barings Private Credit Corp 0001859919 (sandbox `ba1e`; built alone first as `ba1a`)

Names, the roll-forward note rows (`schedule_row_tags`), PIK-only coupons and the printed rate
column were set in earlier rounds (D-094). Built alone with those: 45 outstanding, published 6.9M
under filed at 2023-06-30, equal in the other twelve quarters.

- **The 6.9M: two real rows, both restored; published equals filed in all 13 quarters.**
  (1) 'CPCF BPCC LLC ... 1' (c-838, 4,534) carries its exact cost and fair value and also the joint
  venture note's rounded copies on one context. The test "none of its value facts is rounded" took
  it for a note row. Refined in `pipeline/schedule_row_tags.py`: a context is a note row when a
  value column is filed ONLY in rounded form (test added; c-775, a true note row, still goes).
  (2) Finexvet's first tranche (c-329, 2,388) is filed under a member that names no issuer ('First
  Lien Senior Secured Term Loan') and was dropped as a category row. `context_identifiers` may now
  name a context whose member the fund's own `category_marker_re` reads as a category row
  (`pipeline/page_labelled_contexts.py`, test added; a member that names a position is still never
  renamed). Also restores Adhefin International's subordinated loan (c-86, 350, 2024-09-30), read
  on the page above its line.
- **Rates on a sibling context.** `rate_only_contexts: adopt_adjacent` (the Ares setting): seven
  2023 loans get the rate and spread the filer tagged on the neighbouring member (Dwyer 17.0M:
  'SOFR + 5.75 %, 11.1 % Cash'). Three reference rates the date guess then got wrong are corrected
  from the page (Finexvet x2 EURIBOR, Innovad SARON).
- **Benchmarks the page prints by name.** `reference_rate_codes` for BBSY, BKBM, STIBOR, NIBOR,
  SARON, CDOR, CORRA, SONIA, EURIBOR, SOFR, LIBOR, PRIME (legend read): 300 rows change from a
  date guess (BBSY 206 rows 632.1M, BKBM 20, STIBOR 18, NIBOR 13, SARON 12, CDOR 7, others to
  EURIBOR and SONIA).
- **Result.** Ledger 48 outstanding (three more than before: rate-only contexts now joined are
  reported as merged, by design). 11 proposed (six reasons). Left open 37.
- **Open and real, not fixed:** (a) rows printed 'x % Cash, y % PIK' (Amalfi Midco '2.0 % Cash,
  9.0 % PIK'): the fund's rate tag is read as all-in, the PIK exceeds it, so the row publishes no
  rate (these are the 13 financial_convention_unresolved findings and part of X02); the all-in rate
  is cash plus PIK for those rows. (b) Coastal Marina: the filer tags the 8.0 pct cash loan with
  the PIK concept in five quarters (8M a row); not corrected. (c) Cardinal Senior Loan Fund member
  interest (40.5M, 2026-03-31) is classed private credit. (d) cost on the rows where the
  roll-forward twin had been published (reading 3d) was not re-checked after the changes.
  (e) F26 x7, F27, C103, two merged-context findings: not read.
- Tests: `tests/test_schedule_row_tags.py`, `tests/test_page_labelled_contexts.py`,
  `tests/test_issuer_name_strip.py`: 28 pass.
- **Effect of the two refined tests on the other funds that use them (sandbox `chk1`).** Silver
  Point, TCW Direct Lending VII and VIII, T Series, HPS Corporate Capital Solutions
  (`cost_or_percent_unrounded`) and NexPoint, Overland, Lord Abbett (`context_identifiers`), built
  together and compared with their latest earlier sandbox (`i1a`, `d1a`, `b2a`, `s1c`): the same
  row count and the same published fair value in every one of 86 fund-quarters
  (`scratch/2026-10-11_shared/compare.py`). Other fields were not compared.

### D-104 TPG Twin Brook Capital Income Fund 0001913724 (sandbox `tb1c`; built alone first as `tb1a`)

`rate_tag_reading: coupon_with_margins` was set in D-096 without a page read. Built alone: no loan
lacks a rate in any quarter; the rows the reading lists (Spectrum revolver 'S + 6.25 % 10.50 %',
BPCP 10.10, BBG 12.21) publish the printed coupon.

- **The verifier was re-reading the wrong tag.** Ten provenance findings (119 rows) said the
  published rate differed from the filing. The re-verifier took the first rate fact on the
  context, the cash margin; the published rate is the plain tag and matches the page. For a fund
  with `rate_tag_reading` it now re-reads the plain tag (`pipeline/provenance_reverify.py`). All
  7,375 rates of this fund verify. BlackRock Private Credit and BlackRock Direct Lending use the
  same setting; not rebuilt here.
- **A promoted fleet correction was wrong and is pulled.** `agent_b2_corrections/0001913724/
  column_remap.json` moved the spread of four SimiTree rows into the PIK rate at 2025-12-31 (the
  signed-off quarter). The filer tagged the PIK margin 1.75 instead of 0.0175. Row corrections set
  spread 5.25 and PIK 1.75 on three rows ('S + 5.25 % + 1.75 PIK 11.10 %') and spread 7.00, no PIK,
  on the revolver. That is seven of the ten `column_remap` corrections at 2025-12-31 found harmful
  (D-095, D-096); Audax and Silver Capital are still unread.
- **Reference rates from the page.** Column 'Reference Rate and Spread', codes S=SOFR, T=CORRA,
  P=PRIME (legends of 2023-03-31 and 2026-03-31; the 2023 legend lists no LIBOR). 401 rows change:
  the 2023-03-31 and 2023-06-30 loans had been published LIBOR by date guess.
- **Totals.** The 16,000 roll-forward row at 2026-03-31 is removed (rule extended to the second
  vehicle, still pinned to that quarter). Published equals filed in every quarter.
- **Result.** Ledger 36 outstanding to 25. 15 proposed (six reasons). Left open 10: fixed coupons
  the filer tags as a spread on a few small rows (C115 x2, fmt_basis_spread x2: Spectrum 18.00,
  Canadian Orthodontic 17.00, Kaizen 5.00; the page reading did not convert them), F16 x4 and
  F33 x2 (start-up quarters, not read).
- **Not done:** loans printed 'S + x % PIK' publish the margin as a PIK rate with no spread (5 to
  18 rows a quarter; the D-092 question); 2022-12-31 has a schedule on the page and no tags;
  2023-06-30 doubled member names (7 rows, 38M); the two roll-forward rules stay hand-listed.

### D-105 Antares Strategic Credit Fund 0001993402 (sandbox `as1d`; built alone first as `as1a`)

The commitment-table rows were already excluded by rule. Built alone: 70 outstanding, published
3.3M to 4.2M above filed in three quarters.

- **The plug is gone.** Rule `add_blackrock_short_term_investment_2025` added the money market
  fund with a fair value set to the residual (61,955 / 46,814 / 75,879 against a printed 58,644 /
  42,836 / 71,644): pulled. So is the fleet correction that added the 2026-03-31 row with no class.
  The tagged row now publishes as a cash row with its filed value (`cash_identifiers`, two
  spellings, 2025-06-30 on). Published including that row equals the printed 'Total Investments at
  fair value' exactly in all four quarters; in the five earlier quarters the fund prints the money
  market fund outside the total and published equals filed without it (2025-03-31: 0.294M over,
  two subtotal rows, open).
- **Reference rates from the page.** Column 'Reference Rate and Spread'; S, SON=SONIA, E, P,
  C=CDOR to 2025-09-30 and CORRA from 2025-12-31 (the filer's own tag member changes name then).
  115 rows change (PRIME, CDOR / CORRA, SONIA had been published SOFR).
- **Names.** Twin suffix ' One' to ' Four' stripped (39 rows); 'Diversified Consumer Service' and
  'Speciality Retail' added as industry labels (the filer's spellings; 67 rows lose the industry
  from the name); two rows the filer tagged with no issuer named from the page (WST USA Holdco
  0.9M; Enverus, whose member text is a spreadsheet error message).
- **Fund level.** Shares outstanding 2026-03-31 86,731,536 and 2025-09-30 74,543,881 (pages).
- **Result.** Ledger 70 to 45 after one more check-accepted X02 entry. 32 proposed (seven
  reasons); 13 left open: A01 x4 (labels, not read line by line), C201 x3 and C206 x2 (labels with
  no space or no 'Asset Type' marker; a few rows), X05 (Apex spread 0.0 for a printed 5.00), X01
  2025-06-30 (Accelerate Topco carries the next line's 10.50 pct PIK), C107, X02.
- **Conservation flags at three quarters are a check problem, proposed as such, not silenced:**
  the check adds a stale cash-equivalents figure (62,915,000 in five quarters) to an investments
  line that already includes the fund. I did not write a verified total into the anchor store.
- **Not done:** principal is the commitment, not the drawn amount, on about 190 rows a quarter
  (as filed; changes what principal means); equity unit counts to 2025-06-30; the stale fund-level
  cash-equivalents figure; 'Debt Investments <industry>' prefix on 45 small rows.

### D-106 Owner rulings 2026-10-11 ("1. yes 2. no 3. commit, then keep going")

- **No proxy cost (ruling 1: "yes").** A row with no filed cost publishes no cost.
  `config.COST_PROXY_ENABLED = False`; `financial_conventions.cost_proxies(..., enabled=)`; the
  cost-donor audit records method 'not_filed'. All funds. Tests: one added; the finalizer test of
  the proxy path now switches it on; two tests that pinned the exact set of funds with a PIK
  setting (already out of date) now require the named funds as a subset. 83 pass.
  Checked in sandbox `r1a` (North Haven, Fidelity Private Credit Co): no proxy-cost row.
  Not measured: the number of rows that lose a cost across the cohort (Blue Owl Technology alone
  had 631, 14.5M), and what any return or income series does with a missing cost.
- **A cash-axis member that names no cash is not cash (ruling 2: "no").** Measured first on the
  published build of 2026-10-01: 46 distinct cash-axis members, 45 name a money market, treasury
  or liquidity fund (or the filer's 'Non Money Market Cash'); one does not,
  'InvestmentMeasuredAtNetAssetValueMember' (North Haven, 2 rows, 184.5M). A keyword test for
  "names cash" would have dropped real funds ('JP Morgan US Government', 'Black Rock Federal FD
  Institutional Eighty One'), so the shared rule in `pipeline/staging_bdc.py` instead excludes a
  cash-axis member that names a fair-value-hierarchy category (measured at net asset value, fair
  value level, fair value measurement); such a row is not a position and is dropped. North Haven's
  fund rule `exclude_fair_value_hierarchy_nav_row` is removed as redundant. `r1a`: the North Haven
  row is gone by the shared rule (6,978 rows, as in `n1b`); Fidelity's 12 cash rows (218.7M) stay.
  17 cash and money-market tests of `tests/test_unified_holdings.py` pass.
- **Commit 911dc26** holds D-099 to D-105.

### D-107 Ares Core Infrastructure Fund 0002031750 (sandbox `ac1b`; built alone first as `ac1a`)

- Built alone with the settings of earlier rounds: published equals filed in all seven quarters;
  the two fixed-rate subordinated loans (141.5M at 2026-03-31) publish Fixed with no spread, as
  printed ('9.25 N/A 9.25').
- **Names.** Every row had the instrument in the issuer name and no instrument description
  ('CMH01 Holdings LP, First lien senior secured loan'). Split by `issuer_name_strip_re` with the
  instrument kept: 128 distinct names to 80 over 235 rows; the filer's change of wording at
  2025-12-31 ('loan' to 'loans') no longer breaks every name.
- **One filing error.** 2025-03-31: Aspen's unit count sat on Denali's context. Corrected from the
  page (Denali 3,749; Aspen 4,900).
- **Result.** Ledger 32 to 30. 19 proposed (seven reasons). Left open 11: the first two quarters
  publish percent of net assets 2.2422 and 2.1677 for a printed 224.22 pct and 216.77 pct (the
  ratio-to-percent step skips a ratio above 1; pct identity x2, F22 x2, F23 x2; shared scale
  logic, real, not fixed); inception-quarter fund-level flags (F16 x2, F33, F30); income_identity
  2024-12-31 (not read).
- **Not done:** unit counts are filed a thousand times larger from the 2025 10-K on (Denali 3,749
  then 3,749,000) while the page prints the same figure; published as filed. Controlled vehicles
  are not flagged as subsidiaries. NAV per share is a blend across share classes from 2025-09-30.

### D-108 Industry labels: found while comparing Ares Core, applies to every fund (not fixed)

- `gics_sub_industry` is filled by a language-model labeller keyed on the company NAME, with a
  cache (`company_gics_cache.csv`, `pipeline/gics_classification.py`). It is not read from the
  industry heading the filer prints above every row. Labels already in the cache can be plainly
  wrong: Denali Equity Holdings, a renewable-energy holding vehicle, was 'Advertising'.
- In a fund sandbox the labeller cannot run (no API credit, and I may not make that call), so a
  name the cache has not seen gets no label. Cleaning names therefore removed labels. Non-cash
  rows with no label, before and after (`scratch/2026-10-11_rulings/gics_nulls.py`): North Haven
  2,189 to 2,705; Monroe 6,019 to 6,678; Blue Owl Technology 324 to 668; Ares Core 98 to 140;
  Barings 3,142 to 6,156 (mostly from the name changes of the earlier round, D-094); MSD and Twin
  Brook unchanged; Antares Strategic 5,512 to 4,168 (better).
- Even before today roughly half of these funds' rows had no label. A build with the labeller
  available would fill the new names, by a guess from the name.
- Owner question: read the industry from the filer's printed heading (and map that to GICS) rather
  than guess it from the name. Until then the published industry field is weak and today's name
  clean-up makes it emptier in fund sandboxes.

### D-109 Industry read from the printed heading (owner ruling 2026-10-11: "yes, read industry from the printed heading")

- **What was there.** The page reader already recorded the heading above each row in the
  field-status artifact (`gics_sector`, status `value` on nearly every row). Nothing published it.
  In a cache-only build the published label came only from the name-keyed cache.
- **What changed (all funds, no model call).**
  1. `pipeline/staging_bdc.py` / `bdc_xbrl_html_bridge.apply_ixbrl_field_status_overlay`: the
     printed heading goes to `extracted_industry` where the member itself gave no industry. A
     heading that names an affiliation block, a commitments table, a column, a total, a joint
     venture block or a share class is not taken (`_NOT_AN_INDUSTRY_RE`).
  2. `pipeline/unified_holdings.py` `_apply_printed_industry`: where a BDC row carries the filer's
     industry and that label maps to a GICS sub-industry through the reviewed table, an exact GICS
     name, or an earlier mapping of the same label kept in the label cache, the mapping replaces
     the name-keyed label. A row whose label does not map keeps the label it had.
  3. `pipeline/gics_mapping.py`: 25 headings added to the reviewed table (my choices, e.g.
     'Insurance Services' to Insurance Brokers, 'FIRE: Real Estate' to Real Estate Services,
     'Renewable Energy' to Renewable Electricity).
- **Measured on the eight funds processed so far, built together (sandbox `in2a`), against each
  fund's sandbox of 2026-10-11** (`scratch/2026-10-12_industry/compare.py`). Non-cash rows with no
  standard label, before to after: MSD 974 to 4; North Haven 2,705 to 103; Monroe 6,678 to 807;
  Blue Owl Technology 668 to 100; Barings 6,156 to 718; Twin Brook 5,324 to 341; Antares
  Strategic 4,168 to 2; Ares Core 140 to 21. Rows carrying the filer's own industry: 3,614 to
  41,583 of 43,990. Row counts and fair value by fund are unchanged. 34,293 rows changed label.
- **What the label now means.** The sector (11 groups) follows the filer's heading. The
  sub-industry is one representative pick per heading: a filer heading such as 'Services:
  Business' or 'Healthcare & Pharmaceuticals' is broader than one GICS sub-industry, so the
  published sub-industry (Diversified Support Services; Pharmaceuticals) is finer than what the
  filer states. `extracted_industry` holds the filer's words.
- **Left without a mapping on purpose** (524 rows in these funds; they keep the name-keyed label):
  headings that name no industry: 'Structured Product', 'Consumer Cyclical', 'Other Financial',
  'Industrial Other', 'Credit Card ABS', 'Multisector holdings', 'Other Investments'.
- **Also in this build (ruling of D-106):** rows with a cost fall where the proxy is gone: Blue
  Owl Technology 3,666 to 3,035, Monroe 8,523 to 8,500, Antares 7,039 to 7,022.
- **Not checked:** the 2,068 rows mapped through the label cache rest on earlier model mappings of
  the label (stable, not reviewed); whether the heading the page reader attaches is the right one
  for every row (a row under a continued heading across a page break); funds whose page was not
  read; the frontend industry donut, which reads `gics_sub_industry`.
- Tests: `tests/test_printed_industry.py` (5 new); with the mapping and page-reader test files 192
  pass. Full suite not run.

### D-110 Sixth Street Specialty Lending 0001508655 (sandbox `ss1c`; built alone first as `ss1a`)

- Built alone: 130 outstanding, published 1.0M above filed at 2023-12-31.
- **Totals.** The 1.0M was one position published twice: the filer tagged the printed
  local-currency value '(EUR 890)' as a second fair value on a member spelled 'Price fx Inc.'.
  Removed by a one-quarter rule. Published equals filed in all 13 quarters.
- **Reference rates from the page.** Column 'Reference Rate and Spread'; SOFR, S / SONIA, E, L,
  B=BBSY, N=NIBOR, STIBOR, P, C=CDOR to 2024-03-31 and CORRA from 2024-06-30 (legends of
  2023-09-30, 2024-06-30, 2024-12-31; the switch quarter for C is taken from those two legends,
  the two filings between were not read). 116 rows change: SONIA 47 rows (462.3M), BBSY 15
  (331.1M), CDOR 13 (312.6M), STIBOR 12, NIBOR 9, PRIME 15 had been published SOFR or nothing.
- **Names.** The reader's tested patterns installed in `staging.leaf_guard` (heading and industry
  prefixes such as 'and Leisure ...', 'Structured Credit Investments ...', more instrument
  markers, trailing punctuation): 380 rows renamed, 351 distinct names to 331. Not reached by
  pattern (code-side): CLO rows written 'Series 2020 -4A', a byte-order mark in two members,
  16 members that name no issuer.
- **Fund level.** NAV per share corrected from the page in five quarters (17.17, 17.19, 17.12,
  17.17, 17.14); each had held the value of the same quarter a year earlier.
- **Class kept.** Three Khoros earnout rows lost their class when the name was split (the
  name-keyed cache again); restored by row correction.
- **Result.** Ledger 130 to 105. 44 proposed (six reasons). Left open 61, among them real and
  unfixed: fixed-rate loans published as floating with spread equal to coupon (C115 x8,
  fmt_basis_spread x9); principal tagged negative on 40 rows of 2023 (C110, fmt x9); positions
  printed with a dash for fair value dropped (Astra second lien, cost 39.5M); one position tagged
  across two members (162.4M at 2023-09-30); structured-credit rows classed direct lending (60
  rows, 116M); three phantom fund-level rows dated after the last filing; distribution per share.
- Industry headings added to the reviewed table for this fund ('Internet Services', 'Human
  Resource Support Services', 'Office Products'); they apply at its next build.

### D-111 Share counts replaced by another row's: found on Sixth Street, applies to every fund (not fixed)

- `pipeline/unified_holdings.py` (`with_shares_fix`) treats all rows of one fund with the same
  issuer NAME as one position, compares fair value per share with the group median and replaces an
  "outlier" share count with the nearest other row's (`shares_held_source = 'derived_proxy'`).
  An issuer with two share classes is not one position. With names split from the instrument, more
  rows share a name: IRGSE Class A units, labelled '(33,790,171 units)', now publish 8,800,000;
  ReliaQuest Series A preferred '(1,667 Units)' publishes 16,957.
- Size: 1,653 share counts in 92 funds carry this proxy in the published build of 2026-10-01. In
  the funds processed here it rose with the name clean-up: Sixth Street Specialty Lending 8 to 17,
  Barings 12 to 52; unchanged in the other six.
- Same kind of invention as the cost proxy the owner switched off (D-106), but for share counts,
  and nothing was changed: no ruling covers it.

## 2026-10-12: eight-hour run (owner: "keep going, leaving all human decisions for the end ... run without interruption")

Human decisions are collected in `docs/investigations/v05_owner_decisions_2026-10-12.md`. Local
commits at checkpoints; nothing pushed or published.

### D-112 Stepstone Private Credit Fund 0001950803 (sandbox `st1b`, before `d1a`)

- **Rates, the largest error in this fund.** The filer changed its rate tags twice. For four
  filings (2024-12-31 to 2025-09-30) the plain rate tag holds the SPREAD and the paid-in-cash tag
  the rate; the pipeline kept the first and published the spread as the rate on 664 to 1,147 loans
  a quarter (median 5.25). For the last two filings only the paid-in-cash tag exists and no rate
  was published on 1,193 of 1,233 and 1,273 of 1,303 loans. Two wrapper-switched readings added
  in shared code and set for this fund:
  - `rate_tag_reading: ["cash_rate_with_plain_spread"]` (`pipeline/rate_tag_reading.py`): the
    paid-in-cash tag is the rate; a plain tag beside it with no spread tag is the spread.
  - `untagged_pik: ["none"]` (`pipeline/financial_conventions.py`): a rate tagged as the cash rate
    with no PIK tag is the whole coupon, labelled `interest_rate:cash_no_pik` and admitted by the
    schema check. The fund's column is 'Cash Interest Rate / PIK Rate' and a PIK row prints both.
  - `filed_rate_reading: ["cash_leg"]` for the earlier filings.
  Result: loans with no rate 5 / 15 / 15 / 16 / 18 / 21 / 39 / 86 / 1,193 / 1,273 by quarter to
  1 / 1 / 0 / 1 / 4 / 2 / 8 / 6 / 5 / 6; median rate 9.78 at 2024-12-31 (was 5.25), 8.70 at
  2026-03-31. Creek Parent 2024-12-31 printed '1M SOFR + 5.25 % / 0.75 % 12.75 %'.
- **Totals.** Twin members told apart by a lower-case or glued suffix are kept
  (`distinct_member_suffix_re` widened); CIFC Funding sub notes are a position (two leaf markers);
  five rows of 2026-03-31 filed without the thousands scale corrected (15 values, each printed
  line quoted). Published short of filed in six quarters before, three now: 2023-09-30 1.2M (Apex
  twin whose label and cost differ), 2024-12-31 2.4M (Campany Roof twin whose member names no
  issuer), 2025-09-30 10.0M (Puma Buyer: the page itself prints 3,829 for a 13,829 loan; owner).
- **Result.** Ledger 48 outstanding. 15 proposed (printed twins flagged as duplicates). Left open
  33: X05 x9, X02 x4, four provenance anchors, the two row-add rules that publish bare rows.
- **Not done:** rows where the filer tagged the single printed rate with the PIK concept and no
  cash tag (2025-03-31 to 2025-09-30, about 80 rows: PIK share overstated); issuer names still
  carry the instrument (1,789 distinct names for 7,812 rows); 2023-09-30 names are the financing
  facility; the hard-coded scale repair for the 2025 10-K stays in `bdc_filings.py`.
- Tests: 256 pass (`test_financial_conventions`, `test_rate_tag_reading`, `test_source_encodings`,
  `test_provenance_reverify`); two added.

### D-113 KKR FS Income Trust 0001930679 (sandbox `kk1c`; a held-back fund, not on the public site; no reader report)

- **Three shared weaknesses found here and fixed (tests added, 94 pass).**
  (1) A named column header with a lettered footnote mark ('Rate (b)') was not recognised
  (`_named_header`). (2) The page reader's "industry heading" for this fund is a statement heading
  ('Supplemental disclosure') on all 2,707 rows; the industry change of D-109 would have published
  it. A heading that covers more than half of a filing's rows (20 rows or more) is now not taken as
  an industry. (3) An industry label with a row number ('Capital Goods 2') maps like the plain one.
- **Industry from the member.** The member is 'issuer | industry N'; `staging.pipe_field_map`
  now declares the industry segment: 2,707 rows carry the filer's industry (GICS industry groups,
  e.g. Capital Goods, Insurance), 2,138 map; one group added to the table.
- **Reference rates.** Column 'Rate', codes SF, SA=SONIA, E, P (legends of 2023-09-30 and
  2026-03-31): 106 rows change (SONIA 44, EURIBOR 26; the 2023-06-30 loans had been LIBOR by
  guess); 24 rows become Fixed. The page prints a spread only ('SF+ 625'), no coupon: no
  interest rate is published for most loans, as filed.
- **Result.** Ledger 90 outstanding (84 before; six new findings from the printed-spread check,
  which now runs for this fund: two rows a quarter printed 'SF+ 500 , 2.0 % PIK' differ from the
  tagged spread; real, not fixed). 24 proposed (netted commitment rows, the owner's ruling of
  2026-10-10). Left open 66.
- **Totals, not solved.** Published is 1.5M to 14.1M above filed in nine quarters although every
  tagged debt commitment is matched and netted. The page also subtracts 'Unfunded Commitments
  ( 80,013 )' in Asset Based Finance and the notes mention 'unfunded equity/other commitments of
  $ 19,594' (2025-06-30), which carry no commitment tag. Lead only; rows not traced.
- 2025-03-31 uses a different member form (214 names for 290 rows, 144 with no instrument): not fixed.

### D-114 Goldman Sachs BDC 0001572694 (sandbox `gs1b`, before `d2a`)

- **Totals.** Three fair values the page prints and the filing does not tag are declared with
  their printed lines (`untagged_values`: Omega Midwest Buyer 4,079 at 2025-12-31; 4,069 and 41 at
  2026-03-31), and Engage2Excel's 903 row, tagged on the prior balance date, is re-dated
  (`misdated_contexts`). Published (without the money market fund) equals filed in all 13 quarters;
  it had been 0.9M to 4.1M under in three.
- **Industry from the member text.** This filer prints the industry in a column and carries it in
  the member ('... Industry Software Interest Rate 11.94% ...'); there is no heading. New wrapper
  option `dispatch.industry_from_identifier_re` (generic code in `_apply_printed_industry`, loader
  in `staging_bdc.py`, test added): 5,571 of 5,858 rows now carry the filer's industry; rows with
  no standard label 1,287 to 100.
- **Result.** Ledger 97 to 92 with check-accepted entries updated. Nothing proposed in this pass.
  Left open, as in the reading: C201 x13 (names), SRC_BDC01 x13 and parser mismatch x12 (twin and
  roll-forward members, not re-read), X02 x13, B01 x13, F27 x11, PP02 x9.
- **Not done:** rows printed with a dash for fair value are dropped (cost 33M to 79M a quarter to
  2025-06-30); 63 share counts carry the proxy of D-111; 861 rows have no instrument description;
  Goldman Sachs Private Credit and Private Middle Market Credit II use the same member form and
  have not been given the industry option.

### D-115 T. Rowe Price OHA Select Private Credit 0001901164 (sandbox `tr1a`, before `l5b`)

- Rates, reference codes, foreign principal were set in an earlier round. Built alone: published
  equals filed in all 12 quarters; 13 findings outstanding (X02 x6, F33 x3, C04 x2, B07, C107).
- **Names.** Prefix 'Investment, Unaffiliated Issuer, ', the row ordinal and trailing lien or class
  words stripped (`issuer_name_strip_re`): 916 distinct names to 207 over 3,282 rows.
- **Industry.** Every row carries the filer's heading; 7 headings added to the table ('High Tech',
  'Retail Stores', 'Cargo Transport' ...).
- **A label made honest (shared).** Where the printed column confirms a date-guessed reference
  rate, `reference_rate_source` now says `ixbrl_field_status`. Before, the value was right and the
  source still said 'inferred' (2,913 of this fund's 3,282 rows), which overstated guessed rates
  in every count. One test that pinned the old label is updated.
- **Not done (real):** every row of 2026-03-31 is classed a loan, although 12 rows (66.4M) sit under
  'Preferred Equity', 'Common Stocks' and 'Asset Backed Securities' on the page; the unit counts
  of those rows are tagged as principal. The fix is a class read from the page section, which also
  serves HPS Corporate Capital Solutions, Stone Point, T Series and Blackstone Real Estate Credit;
  not built. No row has an instrument description (the member carries none).

### D-116 MidCap Financial Investment Corp 0001278752 (sandbox `mc1c`, before `c2a`; a held-back fund)

- **Totals.** Published (before cash equivalents) equals filed in all 13 quarters; it had been
  18.0M over at 2024-09-30 and 12.9M under at 2025-03-31. Three fixes, each read on the page:
  the ExactCare group subtotal 17,843 the filer tagged on a second GrayMatter member (one-quarter
  rule); Cool Buyer's fair value 13,111, tagged twice with the cost concept and never as fair value
  (`untagged_values`); the bare 'Warrants' and 'Unsecured Debt' members read as category rows.
- **A guard added to the industry change (shared, test added).** In the Apollo layout the heading
  above a row is the company group ('Paladone', 'FingerPaint Marketing'); the industry sits one
  heading higher. D-109 would have published 6,021 company-group names as industries. Now, where
  fewer than half of a filing's labels map to the standard list (20 rows or more), that filing's
  unmapped labels are withdrawn. For this fund no filer industry is published (6,021 rows) and
  the label stays the name-keyed one (587 rows with none). Reading the higher heading is not built;
  the same applies to Apollo Debt Solutions and the two Apollo Origination funds.
- **Result.** Ledger 139 to 120. Nothing proposed in this pass. Open as in the reading: group-name
  subtotal and affiliate-table members reported as missing (26; totals tie without them), 13
  maturity-not-past, C206 x11 (names: 1,692 distinct names, the member dumps industry, group,
  entity and lien words), no coupon published on 5,043 of 5,273 loans (as filed: the page prints
  margin and floor only).
- **Not done:** positions carried at a dash fair value are dropped (7M to 26M of cost a quarter);
  money-market rows missing from 2025-06-30; net assets missing in 10 of 13 quarters; Kauffman
  equity row (35K) dropped at 2025-03-31.

### D-117 Stone Point Credit Corp 0001825384 (sandbox `sp1a`, before `l5b`)

- **Totals.** Three rows of the 2025 10-K filed without the thousands scale (Helpsystems 8,182;
  MRI Software 1,888 and 494; each printed line quoted) corrected: 9 values. Published equals
  filed within 0.5M in all 13 quarters (was 10.6M under at 2025-12-31). 2026-03-31 stays 0.1M
  under: the filed total includes two interest rate swaps on the fund's own notes (as filed).
- **Names.** The member was the whole issuer name ('Cliffwater, LLC, First Lien Term Loan, Due
  9/30/2030'); split at the instrument words with the instrument kept: 958 distinct names to 283
  over 2,939 rows; rows with no instrument description 2,939 to 34.
- **Result.** Ledger 45 outstanding; nothing proposed in this pass. Open as in the reading: C04
  x13 (units tagged as par on equity rows), X02 x6 and X01 x6 (PIK-only notes; equity rows classed
  as loans, 21M), C206 x5, B01 x8.
- The filer's industry is read on 1,487 of 2,939 rows (all mapped); the other half of the
  quarters have no heading reading.

### D-118 Diameter Credit Co 0001916099 (sandbox `di1b`)

- Published equals filed in every quarter. Names: tranche words stripped from the issuer and put
  in front of the instrument text (shared refinement of `_strip_issuer_names`, test added): 254
  distinct names to 136 over 836 rows. Industry: the filer's heading on 835 of 836 rows, all mapped.
- The 225 loans with no rate are undrawn lines whose member carries no rate (as filed).
- Ledger 34 outstanding, unchanged; nothing proposed. Open as in the reading: C206 x6 (a few rows
  whose member is a maturity date or the whole identifier), F33 x6 (distribution per share taken
  from a preferred-dividend tag: 0.0 for a printed 0.63; fund-level extractor), rows printed with a
  dash for fair value dropped (2 to 17 a quarter), F27 x4, C04 x4, B01 x4.

### D-119 Carlyle Credit Solutions 0001702510 (sandbox `ca1b`)

- Published equals filed in every quarter (the 62.5M of 2024-12-31 was re-dated in an earlier
  round). Names: the member is '<lien>, <issuer> [n], <industry> [n]'; lien prefix, row numbers
  and the trailing industry (the fund's own 38 printed industries) stripped, plus a filer glitch
  that prefixed 'SPF Borrower, LLC, Healthcare & Pharmaceuticals 2' to other issuers at
  2024-06-30: 654 distinct names to 345 over 2,526 rows (1,520 rows renamed).
- Ledger 30 outstanding; nothing proposed. Open: F16 x16 (fund-level, not read), C115 x6 and
  fmt_basis_spread x5 (the equity table's 'All-In Rate' tagged as a spread on one row), FX03
  (Project Carbo cost tagged in euro), 1,520 rows with no instrument description.

### D-120 Fidelity Private Credit Fund 0001920453 (sandbox `fi1c`, before `d1a`)

- **2025-06-30, 104.9M missing.** Twelve positions have their fair value tagged on a context dated
  2025-03-31 inside the 10-Q for 2025-06-30; the current context carries cost and no fair value.
  Each current context is paired with the prior-dated context of the same member from the tagged
  facts (`scratch/2026-10-13_b6/fi_pairs.py`) and its value declared (`untagged_values`, 13
  entries; printed e.g. 'Dpt Management, LLC ... Term Loan SOFR + 5.25 % 9.58 % 12/18/2027
  23,938,607 23,741,489 23,794,975'). Only the Dpt line was read on the page; the other eleven
  rest on the member match and on the total, which now ties.
- **2025-03-31, 60.6M over.** Two industry subtotals tagged on revolver members (RxStrategies
  52,262,801; EDS Buyer 8,306,361) removed by a one-quarter rule.
- **Result.** Published equals filed in every quarter but 2023-06-30 and 2023-09-30 (12.8M and
  46.4M under: a money market fund and central-fund rows of 2023 that are not published; cash
  class by the owner's ruling, so outside the investments comparison once published). Ledger 50
  to 38. Nothing proposed. Open: B01 x8, X02 x7, C04 x7, four conservation flags of 2023.

### D-121 Trinity Capital 0001786108 (sandbox `tn1b`)

- 2026-03-31: two Metabolon loans tagged wholly on a 2025-09-30 context while printed in the
  current schedule ('... 5,230 5,247 5,272' and '... 2,595 2,591 2,604'; 'Total Metabolon, Inc.
  52,613 52,632 53,477') re-dated (`misdated_contexts`). Published equals filed there (was 7.9M under).
- Six quarters keep small gaps, each explained in the reading and not fixed: NextCar twin loans
  whose members differ by one non-ASCII space (0.7M to 0.8M, three quarters); warrant rows with a
  cost and no fair value at 2024-09-30 (3.5M); one extra row at 2024-03-31 (4.6M); 2023-12-31 2.5M.
- Four industry headings added to the table ('Real Estate Technology', 'Software as a Service
  ("SaaS")' ...). 51 share counts carry the proxy of D-111.
- Ledger 88 outstanding; nothing proposed. Open and real in the reading: the published rate is the
  floor rate on variable loans (F27 x12: income yield 3.8 to 7.0 points above the holdings rate);
  zero-fair-value rows dropped (28 to 77 a quarter); issuer name missing on 1 to 8 rows a quarter.

### D-122 Golub Capital BDC 4 0001901612 (sandbox `gb1b`)

- Published equals filed in every quarter. Names: the member is 'issuer, One stop 1'; the
  instrument words and row number are stripped and kept as the instrument: 1,379 distinct names to
  317 over 6,579 rows; rows with no instrument description 5,659 to 2. One heading added to the
  table ('Healthcare Equipment & Supplies'): rows with no standard label 98 to 16.
- The 2,118 loans with no rate are undrawn lines with no rate tag (as filed). The harmful
  `column_remap` of this fund was pulled in an earlier round (D-097).
- Ledger 28 outstanding; nothing proposed. Open: pct_of_net_assets_identity x12 and F27 x6 (not
  read in this pass), C115 x2, X02 x2.

### D-123 Nuveen Churchill Private Capital Income Fund 0001911066 (sandbox `nu1b`, before `nu1a`)

- **Names were being cut at the legal form.** In the older member form ('Kenco Group, Inc.',
  '..., LLC 2') the comma before 'Inc.' or 'LLC' was read as the issuer / instrument separator:
  issuer 'Kenco Group', instrument 'Inc.' on 1,804 rows. The wrapper's split condition now leaves a
  comma before a legal form alone, and the row number is stripped: 2,405 rows renamed, 1,219
  distinct names to 873; the false instruments are gone (the member carries none in that form).
- Ledger 35 to 27 (C202 x4 and fmt_issuer_name x4 cleared). Published is 5.4M to 16.0M under filed
  in the three 2023 quarters: the reading found the filed figure includes cash equivalents there
  (as filed); nine conservation and ten GAV-type findings rest on that and are not proposed here.
- 148 share counts carry the proxy of D-111 (44 changed value with the names).

### D-124 BlackRock Private Credit Fund 0001902649 (sandbox `bk1a`)

- Built alone with the settings of earlier rounds: published equals filed in every quarter; 2 of
  3,994 loans without a rate; names and instruments split; 22 findings outstanding (A01 x9, C04
  x4, negative-principal formats x6, B02, X02, F33). Three industry headings added to the table.
  Nothing else changed; nothing proposed.

### D-125 HPS Corporate Capital Solutions 0001989817, T Series BDC 0001885968, New Mountain Guardian IV 0001925531

Each built alone with the settings of earlier rounds (sandboxes `hc1a`, `ts1a`, `ng1b`).

- **HPS Corporate Capital Solutions:** published equals filed in every quarter; 12 findings
  outstanding (X02 x5, F27 x4, C107 x2, income_identity). No change. Open in the reading: equity
  classed as loans (up to 145M), no instrument description on 1,826 of 1,837 rows (the member
  names none), filer industry on 1,044 rows.
- **T Series BDC:** 25 outstanding; published 1.7M under filed at 2024-12-31 only. No change. Open:
  X02 x8, F27 x8, four conservation flags, the Surewerx row the filing did not tag (0.2M), BP
  Purchaser cost on a prior-dated context.
- **New Mountain Guardian IV:** names split from the lien words with the instrument kept
  (`issuer_name_strip_re`): 568 distinct names to 227 over 3,532 rows; rows with no instrument
  1,340 to 9. Ledger 22 to 21. **Cost of the clean-up:** rows with no standard industry label rose
  from 861 to 1,054, because this fund's industry cannot be read yet: the page prints the company,
  then the industry on the next line, and the reader takes the company as the heading (183
  "headings", all withdrawn by the guard of D-116). Same layout in New Mountain Private Credit.
  The 1,315 loans with no rate are undrawn rows that print none (as filed).

### D-126 New Mountain Private Credit 0002037804, Blackstone Private Real Estate Credit 0002049733, AB Private Credit Investors 0001634452, KKR FS Income Trust Select 0001975736

- **New Mountain Private Credit** (`np1a`, held back): published equals filed; 42 outstanding, 41
  after a check-accepted entry. No change. Industry cannot be read (same layout as Guardian IV).
- **Blackstone Private Real Estate Credit** (`br1a`): 1 finding outstanding; published equals filed.
  All 379 rows are classed direct lending, with no industry and no instrument description (the
  member is the property or sponsor name). Its class is an owner question.
- **AB Private Credit Investors** (`ab1b`): the industry is the member segment after the issuer;
  read by `industry_from_identifier_re`: rows carrying the filer's industry 341 to 5,228 of 6,762;
  rows with no standard label 2,801 to 1,065. A guard was added to that option (shared, test
  added): a rare catch that maps to nothing ('Term Loan', an issuer name, where the filer's
  segments are out of order) is not taken. 'Services' (348 rows) and 'Consumer Non-Cyclical' (140)
  are the filer's own broad labels and stay unmapped. Ledger 66 outstanding, unchanged. Open in
  the reading: no rate tags at all in the two filings of early 2023 (383 and 398 loans; the page
  prints them), 781 loans without maturity, F26 x10, F21 x10.
- **KKR FS Income Trust Select** (`ks1a`, held back): given its sister's settings (rate column
  'Rate', codes, industry segment): filer industry on 1,625 of 1,926 rows. Published is 1.7M to
  9.7M above filed in five quarters, the same unexplained excess as its sister (D-113). 43
  outstanding.

### D-127 Bain Capital Private Credit 0001899017 (sandbox `bn1b`, before `bn1a`)

- **Totals.** Four rows filed unscaled corrected from the page (KAMC Holdings 32,556 and 943 at
  2025-09-30; Spotless Brands and Spindrift at 2025-12-31; 8 values). Published equals filed in
  both quarters (was 33.5M and 11.2M under).
- **Names.** The issuer carried the instrument and 'SOFR Spread' ('AEG Vision First Lien Senior
  Secured Loan SOFR Spread'); stripped with the words put in front of the instrument text: 950
  distinct names to 390 over 2,030 rows. Rows with no standard label rose 264 to 346 with the names.
- Ledger 80 to 71; nothing proposed. Open in the reading: C04 x9, B01 x9, nav identity x5 and the
  GAV-type findings (fund-level figures), fund_strategy x3.

### D-128 APS BDC 0002083477, Jefferies Credit Partners 0001959604, Antares Private Credit 0001976336

- **Shared: a column header with a superscript glued on is still a header.** APS prints
  'Portfolio Company1', 'Interest Rate2', 'Cost3'; the page reader counted the digit as data and
  never recognised the header row, so no printed field was read. Fixed in the header detection
  (`_detect_header_map`). APS (`ap1c`): loans without maturity 131 to 1, reference rate guessed
  from the date 130 to 0 (rate column named in the wrapper). 2 findings outstanding (F28, X02).
- **Shared: 'Software, continued' is the heading 'Software'.** The continuation word is dropped
  when the printed heading is taken as the industry. Jefferies (`jf1b`): rows with no standard
  label 68 to 0 (203 rows had a 'continued' heading). 11 outstanding, unchanged. 1,555 of 1,563
  Jefferies loans publish no interest rate: the schedule prints the spread only ('S + 4.75 %'),
  no all-in rate, and none is tagged. As filed; not a finding to fix.
- **Antares Private Credit** (`an1b`, before `an1a`): given its sister's settings (D-105): rate
  column and codes (reference rate guessed 95 to 0; 82 rows SOFR to PRIME and similar from the
  page), row-number words stripped from 41 names. The money-market row of the last three quarters
  is now the filing's own tagged row (`cash_identifiers`), and the two rules that added it by
  hand are pulled (`_pulled_replaced_by_tagged_row_2026-10-13`): same values (29.0M, 56.0M,
  43.0M), now with accession and class. Published still equals filed. Ledger 47 to 32.

### D-129 Fortress Private Lending Fund 0002012139 (sandbox `fo1b`, before `fo1a`)

- **Shared: a header with a footnote list is still a header.** 'Amortized Cost (3,5)' and 'Fair
  Value (4,5)' were counted as data, so the header row was not recognised. The footnote strip now
  takes lists. Fortress: 303 rows now read their reference rate and maturity from the page; 20
  rows change from a date-guessed SOFR to the printed CORRA / EURIBOR / SONIA; guessed 12 to 3.
- Foreign principal converted with the reference rate (`principal_usd_reference`): 18 rows, FX01
  x4 cleared. Ledger 17 to 13. Published equals filed.
- **Not fixed: net assets at 2025-06-30.** The page prints total assets 346,971, liabilities
  345,967, net assets 1,004 (thousands): a seed quarter with 335M of investments on 1.0M of net
  assets. The pipeline publishes net assets 1,004,000,000 and no total assets. A fund-level
  correction was written and logged as applied, but the scale detector that runs after it
  (`fund_financials.py`, 'TA/NA ratio' fix) re-scales the row because the ratio is 346 against a
  median near 1.5, so the correction had no effect and was withdrawn. Five findings (A07, PCT01,
  pct identity, F21, F23) rest on it. Needs a rule that a page-corrected figure is exempt from
  scale detection. Also open: percent of net assets tagged as 24.28 for a printed 2,428.
- Two rows per quarter with no ' Investment ' word in the member have no issuer (C201 x2).

### D-130 Fidelity Private Credit Company 0001899996 (sandboxes `fc1a`, `fc1b`, `fd1a` with its sister)

- Built alone: published equals filed in every quarter but 2023-06-30 (1.4M under). 43 findings
  outstanding (F27 x12, B01 x9, C04 x8, X02 x6). The 432 loans without a rate are undrawn lines
  that print none (26 to 49 a quarter, fair value near zero): as filed.
- **New wrapper option `dispatch.instrument_description_strip_re`** (shared code, test added): the
  filer's header words are removed from the instrument text. Fidelity's member carries its column
  headers ('Type Term Loan Reference Rate and Spread SOFR + 5.25% Interest Rate 9.58% Maturity
  Date 12/18/2027'). Set on both Fidelity funds: 2,220 and 2,215 rows now read 'Term Loan',
  'Delayed Draw Term Loan', 'Class A Units'. No other column changed, no row moved, ledgers
  unchanged (43 and 38).
- Not done: 25 rows of 2023 whose issuer carries the industry in front ('Building Products,
  Copperweld Investor, LLC'); 15 proxy share counts (D-111).

### D-131 VISTA Credit Strategic Lending 0001919369 (sandbox `vi1b`, before `vi1a`)

- Published equals filed in every quarter. Rate column named ('Reference Rate and Spread'): the
  152 reference rates of 2023-12-31 to 2025-03-31 that were guessed from the date are now the
  page's (all SOFR, so no value changed; the source did). Guessed 152 to 0. Nothing else moved.
- Seven of the fund's own software headings added to the table (representative picks: 'Data &
  Analytics' and 'Diversified Software' to Application Software, 'IT Security' and
  'Infrastructure Software & DevOps' to Systems Software, and so on): unmapped rows 89 to 18.
  Four broad headings are left unmapped on purpose ('Media, Entertainment & Publishing', ...).
- 19 findings outstanding (F16 x6, C04 x3, X02 x2, F33 x2, six single). Nothing proposed.

### D-132 26North BDC 0001950976 (sandbox `tn2b`, before `tn2a`)

- Published equals filed in every quarter. The 262 loans without a rate are undrawn lines that
  print a spread and no rate (one drawn row, 0.8M, at 2026-03-31): as filed.
- **Industry is a column, not a heading, and sits in the member** ('...|Term Loan|IT Services|SOFR
  + 6.500%|...', in three quarters glued to the rate: 'SoftwareSOFR + 6.750'). Read with
  `industry_from_identifier_re`: filer industry on 683 of 687 rows (was 12). The standard label
  changed on 619 rows and the sector on 505: the label derived from the company name was wrong
  for most of this fund (e.g. Adelaide Borrower: 'Application Software' to 'Multi-Utilities').
- Rate column named: 565 reference rates now come from the page; guessed 614 to 49.
- 17 findings outstanding (C04 x6, B01 x5, F26 x2, four single). Nothing proposed.

### D-133 Goldman Sachs Private Middle Market Credit II 0001772704 (sandbox `gp1b`, before `gp1a`)

- Published equals filed in every quarter. Given the settings of Goldman Sachs BDC (D-114):
  foreign principal converted with the reference rate (50 rows; FX01 x12 cleared), rate column
  and codes named (78 reference rates now from the page: 40 GBP loans printed 'SN +' change from
  SOFR to SONIA, 36 printed 'CDN P +' change to PRIME, i.e. Canadian prime under the PRIME code;
  guessed 103 to 31), industry read from the member where staging found none.
- **Shared: a rate left behind the industry is removed.** Where the member writes 'Interest Rate'
  with a non-breaking space the staging split let it through ('IT Services Interest Rate
  10.94%'). Cleaned before the industry is mapped (any fund; test added): 44 rows here.
- Ledger 54 to 42. Open in the reading: B01 x11 (dash-fair-value rows dropped), X02 x8, cost
  conservation x4 (cost sign in the tag on undrawn rows, 53 rows), fund-level figures.

### D-134 Crescent Capital BDC 0001633336 (sandbox `cc1c`, before `cc1a`)

- **Totals.** Published now equals filed in every quarter (was +6.3M, +6.4M, -1.2M in three).
  - Ancora Bidco, 2024-12-31 and 2025-03-31: the issuer's loan subtotal, tagged by the filer on a
    delayed-draw member, was published as a third loan (6,271 = 6,298 - 27; 6,438 = 6,446 - 8;
    cost likewise). Removed by a two-quarter rule with the printed line and the arithmetic.
  - MB2 Dental, 2026-03-31: fair value cell not tagged; declared from the page ('... 02/2031 1,246
    1,238 0.2 1,234', `untagged_values`).
- Safco Dental Supply, 2026-03-31: one row tagged on a Lash Opco member; issuer and instrument
  corrected from the page (row correction; the total is unaffected).
- Two headings added to the table (70 rows).
- **The ledger went up, 45 to 51, and that is the honest reading.** With the subtotal no longer
  published, source reconciliation reports the Ancora fact as a source row with no published row
  (two findings a quarter) and one GAV finding appears. Its subtotal test sums every row of the
  issuer, equity included, so it does not see a subtotal of the loans alone. The check needs
  extending (subtotal of the issuer's rows of one section); until then these are five findings
  whose answer is 'the filing's subtotal, correctly not published'. Not proposed here.
- Open: C201 x13 (rows whose member carries no 'Investment Type' word have no issuer), pct of net
  assets identity x7, X02 x7, 267 guessed reference rates (the page prints 'S + 500' in an
  'Interest Term' column the reader does not take as a reference-rate column), 47 proxy shares.

### D-135 Apollo Origination II (Levered) Capital Trust 0002052152 (sandbox `ao1c`, before `ao1a`)

- Published equals filed. 20 findings outstanding, unchanged. 538 of 557 loans publish no rate:
  the Apollo schedule prints 'S+450, 0.50% Floor' and no all-in rate; as filed.
- **Industry in the Apollo layout is now read.** The page reader takes the company group as the
  heading ('MRO Holdings'); the guard of D-116 withdraws those. The member text starts with the
  industry ('Aerospace & Defense MRO Holdings MRO Holdings, Inc. Investment Type ...'), with no
  separator, so the wrapper lists the fund's industries (`industry_from_identifier_re`, 53 names).
  Shared change (test added): the member is read again after a heading is withdrawn. Filer
  industry on 565 of 565 rows (was 0); the standard label changed on 202 rows, the sector on 98.
- Instrument text no longer carries the rate ('First Lien Secured Debt - Term Loan Interest Rate
  S+450, ...' to 'First Lien Secured Debt - Term Loan', 556 rows, `instrument_description_strip_re`).
- The same two settings are written to the two sister funds (0002052153, 0002006758), measured
  when each is built. **Not applied to Apollo Debt Solutions (0001837532)**, a first-five fund at
  zero outstanding: same layout, same gain available, owner's call.

### D-136 Overland Advantage 0001965934 (sandbox `ov1c`, before `ov1a`)

- 2024-06-30: the filer's member for one Summit Materials loan is cut off ('... Construction
  Materia'), so it read as a heading and was dropped. The context is named in full
  (`context_identifiers`; page: 'Summit Materials LLC First lien senior secured term loan SOFR +
  2.50 % 1/12/2029 3,990 4,026 4,015'). Published equals filed there (was 4.0M under).
- **Five quarters stay 91M to 215M under filed, and the published rows are right.** The filer
  prints a U.S. Treasury bill inside 'Total Investments'; it is published in every one of those
  quarters, classed cash, and the totals check leaves cash out. Gap = the bill to the thousand in
  each quarter. Six conservation and about twenty GAV-type findings rest on this one fact. Owner
  decision: count a Treasury bill printed inside the investments total in the comparison (a
  wrapper statement), or class it as an investment.
- All 461 loans publish no interest rate: the schedule prints the spread only. As filed.
- Three headings added to the table. 44 findings outstanding, unchanged; nothing proposed.

### D-137 NMF SLF I 0001766037 (sandbox `nm1b`, before `nm1a`)

- Names split from the lien words, with the words kept as the instrument (same pattern as New
  Mountain Guardian IV, D-125, plus 'Undrawn' / 'Drawn'): 994 distinct names to 333 over 4,586
  rows; rows with no instrument 2,870 to 131. 277 position ids changed. Ledger 65 to 63.
- **Cost of the clean-up, and a warning about the old labels:** the standard industry label, which
  for this fund still comes from the company name, changed on 900 rows and went missing on 395
  more (979 to 1,374 unlabeled). The same company got a different label once its name lost the
  suffix. Neither set is evidenced; the fund's printed industry cannot be read yet (company line,
  then industry line, D-125).
- Not fixed: published differs from filed in four quarters (-6.1M, +16.4M, +6.9M, +3.0M); 1,534
  loans without a rate (undrawn lines); 2,947 reference rates guessed from the date; F23 x13,
  PCT02 x10, A07 x10, F22 x10.

### D-138 Lord Abbett Private Credit Fund 0002008748 (sandbox `la1b`, before `la1a`)

- Published equals filed in every quarter. Names split from the loan words, kept as the
  instrument ('BCM One Inc Delayed Draw' to 'BCM One Inc' / 'Delayed Draw'): 266 distinct names to
  112 over 650 rows; rows with no instrument 650 to 71. 70 position ids changed. Two rows of
  'Security 101 Inc' now resolve to the entity name 'Security' (entity naming, not the strip).
- **Open, and the largest gap for this fund:** the page reader locates none of its rows (693 'not
  found'), so nothing printed is read: no filer industry on any row (475 without a standard
  label), 515 reference rates guessed from the date, 8 loans without maturity. Cause not looked at.
- 21 findings outstanding, unchanged (B01 x6, PCT01 x4, concentration x4, X02 x3). One
  unclassified row of 48.4M (SBLA Private Credit LLC, the fund's own vehicle) is an owner question.

### D-139 TCW Direct Lending VIII 0001825265 (sandbox `tw1a`)

- Row data is in good order: every loan has a rate and maturity, no guessed reference rate, filer
  industry on every row (two headings added to the table). No fund setting changed.
- 76 findings outstanding, and most are one fund-level error, not fixed: **net assets is read from
  the paid-in line.** Page (0001193125-26-221923): 'Common Unitholders' capital 879,986 ...
  Total Members' Capital 815,597'; published net assets 879,986,000. The extractor takes
  us-gaap:MembersCapital; the right concepts for this filer are MembersEquity or AssetsNet
  (815,597). Cause of F10 x10 and balance-sheet identity x9, and part of pct-of-net-assets
  identity x5. The concept order is shared by every fund (`extract_companyfacts.py`), so changing
  it needs a cohort measurement; a per-fund correction needs ten quarters read from the page.
  Neither done. TCW Direct Lending VII likely has the same error.
- Also open: B01 x10 (reading says false alarm, date-only contexts), cost conservation x5 (two
  real), no filed total found for the first three quarters of 2023.

### D-140 AGL Private Credit Income Fund 0002011498 (sandbox `ag1c`, before `ag1a`)

- Published equals filed in every quarter; every loan has a rate and maturity, none guessed.
- Instrument text cleaned of the member's header words ('First Lien Revolving Loan Industry
  Semiconductors ... Reference Rate and Spread ...' to 'First Lien Revolving Loan', 532 rows).
- Industry read from the member in the two early quarters that had none (82 rows; label changed on
  58, sector on 36). 89 rows of 2026-03-31 still have none: there the member puts the industry in
  front of the issuer with nothing between them.
- Ledger 18 to 19 (one finding more after the instrument change; not traced). Nothing proposed.

### D-141 MidCap Apollo Institutional Private Lending 0002006758 (`ma1a`) and Apollo Origination II Capital Trust 0002052153 (`au1a`)

Both built alone with the Apollo-layout settings of D-135 already in their wrappers (no build of
either before the change exists in this run, so there is no before / after).

- **MidCap Apollo Institutional:** published equals filed in every quarter. Filer industry on
  1,678 of 1,734 rows; 14 rows without a standard label; instrument text without the rate. 1,646
  of 1,681 loans publish no rate (spread only on the page; as filed). 26 findings outstanding
  (spread_printed x6, F27 x6, a source / pipeline-only pair in one quarter, single others).
- **Apollo Origination II (unlevered):** published equals filed. Filer industry on all 576 rows.
  40 of 41 findings outstanding: five source rows unresolved with their row checks (SRC_BDC01 x5,
  C107 x5), four rows with no class and zero value that carry the C30x checks (rows added by a
  rule), C04 x4, spread_printed x3. Not worked.

### D-142 Silver Point Specialty Lending 0001646614 (`sv1b`, before `sv1a`) and TCW Direct Lending VII 0001715933 (`t71a`)

- **Shared: a country is not an industry.** Silver Point groups its schedule by country, and the
  heading read from the page ('Canada', 'United Kingdom', ...) was published as the filer's
  industry on 158 rows. Country names are added to the not-an-industry filter (test added).
  Silver Point now has no filer industry on 1,848 of 1,856 rows and no standard label on 1,081:
  its industry is not read at all. No other column changed.
- **Silver Point: read, not worked.** 123 findings outstanding. The reading says published
  excluding cash equals filed in 8 quarters and that most conservation / GAV-type findings compare
  against a base that includes the cash row. FX01 x11 is real, but the reading warns the
  principal unit tag is not stable, so the reference-rate conversion was not switched on.
- **TCW Direct Lending VII: read, not worked.** 143 findings outstanding. No filed investments
  total is found in eight quarters (the comparison has nothing to compare). F10 x14 and
  balance-sheet identity x13 look like the net-assets concept error of D-139 (same filer); not
  verified on the page. Row data: 5 of 521 loans without a rate, one guessed reference rate,
  filer industry on every row (one heading added to the table).

### D-143 Phillip Street Middle Market Lending 0001948368 (`ps1b`), Crescent Private Credit Income 0001954360 (`cp1b`), Varagon Capital 0001784700 (`va1a`)

- **Shared: a page footer is not an industry.** Crescent Private Credit Income published 'See
  accompanying notes' as the filer's industry on 631 rows (1.36B). Added to the not-an-industry
  filter (test added). Those rows now carry no filer industry (632 of 2,290; 521 without a
  standard label, unchanged): the fund's industry is not read for them.
- **Phillip Street** (a Goldman fund): foreign principal converted with the reference rate (13
  rows; FX01 x6 cleared) and the rate column named (18 rows change from a guessed SOFR to the
  printed rate; guessed 18 to 0). Published equals filed. Ledger 41 to 35. The 639 loans without
  a rate are undrawn lines. 94 proxy share counts (D-111).
- **Crescent Private Credit Income:** foreign principal converted (107 rows; FX01 x6 cleared).
  Ledger 67 to 61. Published 1.5M and 2.3M under filed in two quarters, not traced. Open: C201 x11
  (rows with no issuer), B01 x11, A01 x7.
- **Varagon:** built and recorded, not worked. 64 findings outstanding; published 0.7M to 6.4M
  under filed in at least five quarters; 43 rows with no class (11.1M); C201 x8, conservation x5.

### D-144 Check: MSD and Monroe rebuilt with the code as of the end of the run (sandbox `chk2`, before `in2a`)

Purpose: measure the shared changes made since 2026-10-12 on two funds finished before them.
- Ledger: 103 outstanding for the two together (42 + 63 = 105 when each was finished).
- No value, rate, class, name or maturity changed on any of their 10,350 rows.
- Changed: `reference_rate_source` on 6,242 Monroe rows (a date-guessed rate the page confirms is
  now marked as read from the page; the rate itself is the same); Monroe instrument text on 935
  rows ('Senior Secured Loans' to '(Revolver) Senior Secured Loans': the tranche word taken off
  the name is kept in front of the instrument) with 40 position ids; 4 MSD rows gained a label.
- Entity ids and canonical names differ only because the two sandboxes hold different sets of
  funds. This is two funds, not the cohort: the first five and next five are still unmeasured.

### D-145 Check: the first five funds rebuilt with the code as of the end of the run (sandbox `chk5`, before `final5` of 2026-10-08)

- **Ledger to 2026-03-31: 0 outstanding of 296.** Five more findings show as outstanding (F28 at
  2026-06-30, one per fund): this build ran to 2026-03-31 while fund-level figures for 2026-06-30
  are on disk, so the rule reports a fund-quarter with figures and no holdings. An artifact of
  the check build, not of the code.
- **No fair value, principal, rate, spread, PIK, maturity or lien value differs** on the 65,649
  rows common to both.
- Differences, all traceable to rulings or decisions since 2026-10-08 except the last two:
  - cost withdrawn on 1,151 rows (no proxy cost, owner ruling 2026-10-11; Blue Owl 1,131);
  - `extracted_industry` on 55,509 rows and the standard label on 40,662 (industry from the
    printed heading, owner ruling 2026-10-11). **Not verified row by row for these five funds:**
    the example the diff prints is an Ares row going from 'Automotive' to 'Software & Services',
    which needs a page check before anyone relies on it;
  - issuer names without the row number (BCRED, HPS; 12,413 rows) and the position ids that follow;
  - `reference_rate_source` on 36,889 rows (guess confirmed by the page; values unchanged);
  - **unexplained, to check:** three HPS rows moved from common equity to direct lending; 19
    share counts changed (Ares 9, Blue Owl 6, HPS 4; the proxy of D-111).

### D-146 Next five funds: owner rulings of 2026-10-13 on the proposed dispositions (sandbox `n5r`, with 2026-06-30)

The 82 outstanding findings were explained to the owner in ten groups by reason. Owner (verbatim):
"accept all elements except 3 and 10". Recorded in `next5_owner_accepted.json`
(`make_proposed_dispositions.py`, `OWNER_ACCEPTED`). Ledger: 82 to 16 outstanding of 262.

- **Accepted:** percent of net assets (owner: "id lean towards using recomputed, if total FV's
  match"; the filed percent is on net assets, printed to one decimal, and the recomputed
  `pct_of_net_assets_calculated` is the figure to use where the fund's total ties and net assets is
  confirmed); loans with no rate filed; the Sixth Street subtotal pairing ("so long as total FV
  matches the sum of each position"); start-up quarter ratios; twin tranches; the Oaktree
  joint-venture rows ("skip unpublished JV rows for now") and PP03; the stray prior-period
  members; non-accrual as information.
- **Not accepted, group 3 (members with no fair value, B01 x9).** Owner's point, confirmed: at
  Sixth Street 1,164 of 1,184 such contexts are duplicates of a valued position (same member; the
  duration context carries only the acquisition date). The other 20: 12 are SMA Technologies
  Class B units printed with a dash (a zero-value position, not published); 5 are the same
  duplicates under a changed label; 2 (Severin, Price Fx, 2024-12-31) carry the par amount on its
  own context, so those loans publish no principal; **1 was a missing position.**
- **Fixed: Hippo XPA Bidco, 2024-03-31.** Page: '... STIBOR + 6.50 % 10.58 % (incl. 3.50 % PIK)
  7,281 7,102 (SEK 75,938) 0.3 %'. Cost tagged, fair value not; the row was dropped. Declared
  (`untagged_values`). No filed total had been extracted for that quarter, so the 7.1M gap was
  invisible; the printed total is added ('Total Investments $ 4,197,705 $ 4,277,564'). Published
  now equals it (4,277.6M). The earlier statement that this fund ties in every quarter was wrong
  for this one.
- **Not accepted, group 10: six separate questions,** each re-read on the page 2026-10-13:
  CLO warehouses at 22.10 / 23.10 / 27.20 pct (Ares Strategic Income, as printed); par far above
  value on CLO bottom tranches and Flexsys (as printed); negative values on undrawn lines (Golub,
  as printed); the 10-K and 10-K/A (1,693 fair-value facts each, identical); Camelia Bidco rate
  (published 9.95 equals the page); equity with no unit count: Eclipse Buyer preferred prints a
  dash, but **PB Group LP units print 113 units and none is published** (not as filed).
- **Not done, owner informed:** the checks themselves still run on unpublished joint-venture rows
  (shared validation modules; needs a test and a cohort measurement); twin contexts are not merged
  and no acquisition date is published.
- The script's handling of an entry that replaces a reviewer's verdict changed: the owner can now
  accept one by name (it was always left a proposal, and then dropped from the live file).

### D-147 Next five: one-offs accepted, twin contexts, acquisition date, Golub unit counts (sandbox `n5s`, before `n5r`)

Owner, 2026-10-13, after the page re-read of each one-off: "do as recommended and commit".
- **Accepted (five):** CLO warehouse rates of 22.10 / 23.10 / 27.20 pct and par far above value
  (Ares Strategic Income); negative values on undrawn lines, the identical 10-K and 10-K/A, the
  Camelia Bidco rate (Golub). Each as printed.
- **Golub unit counts (fix, not a disposition).** PB Group Holdings LP units print 113 (thousand)
  units; the filer tags the count with the principal concept. The fund's wrapper now lists 'LP
  units' and 'LP interest' as equity labels (`equity_instrument_labels`), the existing option for
  this: 5 rows gain 113,000 units; nothing else changed. C04 no longer fires.
- **Twin contexts (shared rule fix, test added).** The extractor already merges a position's value
  context with its date-only twin; the B01 check read the raw contexts and counted the twin as a
  position with no value. It now leaves out a context with no value whose member, filing and
  period also have a valued context. Cohort effect not measured: it can only remove findings, and
  only where an identical member carries a value.
- **Acquisition date is published.** New column `bdc_acquisition_date` in the unified holdings
  (the filer's tagged date, BDC only; blank before 1950 or after the report date). In this
  sandbox: Sixth Street Lending Partners 1,169 of 1,238 rows, Goldman Sachs Private Credit 215 of
  5,947, the other three funds tag none. Schema check passes; no existing column changed.
  **Schema change to the central artifact:** not yet in the Parquet / dbt contract documents, the
  baseline, or any 70-fund build.
- **Result:** 246 findings, 2 outstanding for the next five (was 82 this morning); the top ten
  together 2. Both are one question: SMA Technologies Class B units at Sixth Street (142,038
  units, printed with a dash for cost and value, 0.0 pct) in 2023-09-30 and 2023-12-31, a
  zero-value position that is not published. Owner to rule: publish zero-value positions, or
  accept as printed.
- Still open and not findings: Severin and Price Fx (2024-12-31) publish no principal (par tagged
  on its own context under a slightly different member); Rooster BidCo preferred tags 1,601,000
  and 2,000 as principal in two quarters, unit count or not unknown; the validation checks still
  run on unpublished joint-venture rows.

### D-148 Sixth Street Lending Partners: zero-value position published; HPS missing principal traced (sandboxes `sm1`, `t5q`)

- **SMA Technologies Class B units published at zero** (owner, 2026-10-13: "publish SMA at zero").
  The other nine top-ten funds publish zero-value rows where the filer tags 0 (Ares Capital
  1,658, Blue Owl 1,623, Golub 957 ...); this filer tagged units and percent and no value. All
  seven filings print '142,038 units) 11/21/2022 - - 0.0 %' (read on each page). Declared with
  `untagged_values` (fair value 0, cost 0; 14 entries). The position is now continuous from
  2023-03-31 into the quarters where it carries a value. Sixth Street Lending Partners: 48
  findings, 0 outstanding; the top ten together 0.
- **Seen on the same rows, not fixed:** from 2024-12-31 the row's label and tag say 173,048 units
  and the published count is 244. That is the share-count proxy of D-111 replacing a filed count
  with another row's; the owner decision on it is still open.
- **HPS Corporate Lending, 2026-03-31: 522 of 637 drawn loans (20.4B) publish no principal.**
  Cause: in that one filing (0001628280-26-033248) the filer tagged the par column with the
  share-count concept (InvestmentOwnedBalanceShares) on 696 of 835 position contexts; the
  filings before and after use InvestmentOwnedBalancePrincipalAmount on about 95 pct (752 of 784,
  785 of 820, 808 of 847, then 772 of 818). Page: 'Global Music Rights, LLC ... SF + 4.50 % 8.20 %
  12/20/2031 439,167 435,568 443,558'; the 439,167 is tagged as shares. The par is published in
  `shares_held` on those loans and `principal_amount` is empty. Present in the sandbox signed off
  on 2026-10-08; no rule looks for a drawn loan without principal. Not fixed yet.
- Same shape, smaller, cause not read: Ares Strategic Income 144 loans (0.9B), Apollo Debt
  Solutions 12 (0.5B), BCRED 44 (0.4B), Sixth Street LP 5, Goldman Sachs Private Credit 15, Blue Owl 8.

### D-149 HPS par restored; two new rules so the ledger sees missing fields (sandboxes `t5r`, `n5t`, with 2026-06-30)

Owner, 2026-10-13: "fix it. how can such issues be captured in the ledger", then "add the rule".

- **HPS 2026-03-31 fixed.** New wrapper setting `source_encodings.par_tagged_as_units` (a list of
  filings). In a listed filing a row classed as a loan that carries a share count and no
  principal publishes the count as its principal (`principal_amount:from_shares_tag`); the
  provenance re-verifier reads it against the share-count fact. HPS lists 0001628280-26-033248:
  drawn loans without principal at 2026-03-31 go from 522 (20.4B) to 0. Other quarters untouched.
- **Rule X11 (row level): a drawn BDC loan with a fair value and no principal.** Published rows
  only. Fires in 43 fund-quarters of the top ten that were at zero. A first look at the top five:
  BCRED CLO subordinated notes and Ares' SDLP certificates carry the par as a unit count (the HPS
  error, row by row); Apollo's JOA Joker and Jagex loans carry neither; Blue Owl Pluralsight; one
  HPS row named 'Holdings 2, L.P.' classed as a loan. None read on the page yet.
- **Rule `field_coverage_drop` (fund, quarter, field):** the share of rows carrying a field falls
  20 points or more against the fund's previous quarter (eight fields; at least 20 rows; a
  recovery or a first quarter is not a finding). Needs no knowledge of which field will break; it
  finds the HPS quarter unaided. Fires in six fund-quarters, none investigated: Blue Owl
  2023-09-30 (equity units 100 to 25 pct), 2024-12-31 (cost, maturity, industry and percent of
  net assets all to about 69 pct: one block of about 220 rows), 2025-03-31 (percent of net assets
  to 0), 2025-12-31 (industry); Oaktree 2023-09-30 and Goldman Sachs Private Credit 2026-06-30
  (industry to 0).
- **Ledger, top ten:** 49 outstanding (top five 30 of 346, next five 19 of 262), all from the two
  new rules. The earlier zero stood for 'no rule fired', as warned.
- Not added: a row rule for equity with a principal tag and no unit count (it would fire on every
  row printed with a dash; the fund-level C04 covers the bulk). Not built: a floor on coverage
  for a field a fund never carries (the drop rule cannot see that), and a tag-mix check at source.
- Both rules are shared and fire on every fund; their cohort count is not measured.

### D-150 Top ten: the findings of the two new rules worked through (sandboxes `t5u`, `n5v`, `ax1`, `ax3`, with 2026-06-30)

Owner, 2026-10-13: "fix the top 10 new issues". 49 outstanding to 35. What was fixed is data; what
is left is listed with its cause.

**Fixed**
- **Par tagged as a share count on single rows** (`par_tagged_as_units` row modes, per fund; shared
  code). The count becomes the par only where it sits next to the row's cost, multiplied by the
  one power of a thousand that puts it there (a count carries no scale: Goldman Sachs Private
  Credit files 8,770 against a cost of 8,770,000; Ares files 1,289 against 1,288.8M, page 'Senior
  Direct Lending Program ... 1,289 1,288.8 1,237.1'). A row that names units, shares, stock,
  membership or warrants keeps its count. Three modes: `rows_near_cost` (0.8 to 1.25 times cost:
  Blue Owl, Apollo, HPS, Goldman Sachs Private Credit); `rows_within_twice_cost` (0.5 to 2: BCRED,
  whose CLO subordinated notes are bought at a discount, page 'Signal Peak CLO 14 ... 26,000,000
  20,345 20,975'); `rated_rows_near_cost` (the near band and a rate or spread fact: Ares, which also
  tags equity units under loan members, D-018). Rows converted: BCRED 41, Goldman 15, Blue Owl 8,
  Ares 2, HPS 2, Apollo 1.
- **Two mistakes of mine caught by reading the result and reverted.** Ares Strategic Income was
  switched on and off again: its counts are unit counts of asset-backed investments ('Mars
  Downstop Loan Purchaser Trust ... 29,990,339' while cost amortises 28.7M to 8.6M), and the rule
  read them as par in two quarters of ten. And at Ares Capital the near band took 9,750,000
  membership units (APG Intermediate) for a par before the rate requirement was added.
- **Blue Owl 2023-09-30, equity unit counts** (`units_tagged_as_par`, per filing): that 10-Q tags
  the units of 33 of 44 equity rows with the principal concept (57 share-count tags against 94 and
  92 in the neighbouring filings; page 'Minerva Holdco ... Series A Preferred Stock ... 100,000').
- **Blue Owl 2025-12-31, industry:** the upper line of a two-line column header ('Interest') was
  read as an industry heading on every page; the reader now ignores it. 149 rows regain their
  industry.
- **Goldman Sachs Private Credit 2026-06-30, industry:** the member format changed in that filing;
  the industry is read from the member (`industry_from_identifier_re`): 781 rows.
- **Par declared from the page** (`untagged_values`): Sixth Street LP Severin (216,386); Apollo
  McGraw-Hill (33,903), Allied Universal (41,733, cost 41,554), Convergint (26,254, cost 26,147),
  Jagex (68,523, cost 66,965), Waystar (11,933, cost 11,919); Ares Centric Brands (74.2M, cost
  74.1M) and Neptune Bidco (52.8M). Each printed line is quoted in the wrapper script of record
  (`scratch/2026-10-13_q2/par4.py`, `apollo_par.py`, `sev_apply.py`).

**Left, with cause (35 findings)**
- Ares Capital X11 x8: ARES 2007-3R subordinated notes in six quarters (page '20,000,000 - 0.1':
  cost zero, so the band cannot apply); Sunrun, Viant and Murchison rows with no par tag, not read.
- Apollo X11 x5: foreign loans whose par is printed in euros or sterling and not tagged (SumUp EUR
  40,000; JOA Joker EUR 126,725; Version 1 GBP 6,559; Waystone), and one small row. **JOA Joker
  2025-12-31 also publishes a wrong cost:** page 'EUR 126,725 132,847 147,810'; published cost
  126,725,000 (the par figure sits in the cost tag). Not corrected.
- BCRED X11 x2: Pigments Services (the page prints no par for those two lines: as printed) and one
  CLO note with zero cost.
- Blue Owl x6: the commitments table the filer tags from 2024-12-31 (about 220 rows a quarter with
  no cost, maturity, industry or percent; kept under 'keep the undrawn lines') and the percent of
  net assets the filer stopped printing on position rows from 2025-03-31 (both as filed); and four
  PP03 findings that appeared once unit counts and pars were filled (the rule reads a count equal
  to last quarter's as a prior-period row; the reason accepted for Oaktree in D-146).
- Ares Strategic Income X11 x9: asset-backed investments printed with a unit count and classed as
  loans. A classification or rule-scope question, not a missing par.
- Sixth Street LP X11 x4: Price Fx (EUR par on its own context) and three small rows not read.
- Oaktree x1: its industry is printed in a column the page reader does not read.

### D-151 Ares Strategic Income: unit counts on coupon-bearing tranches stay unit counts (owner, 2026-10-13)

- Question put to the owner: the fund's 'Private asset-backed investment' rows that carry a coupon
  and a figure in the Shares/Units column (about 80 positions, mostly CLO tranches) - is that
  figure a par? Evidence: it is the face amount in whole dollars (MDPK 2025-75: 21,935,000 units,
  cost 21,935K; ANCHF 2025-19: 37,070,000 against 34,584K), original face for older and
  amortising positions (Mars Downstop: 29,990,339 throughout, cost 28.7M to 8.6M), and a notional
  for an interest-only strip (JPMMT 2026-ACES1: 1.28B against a 36M cost).
- **Owner: "let's leave it as is".** The count stays in `shares_held`; no principal is published
  for these rows; `par_tagged_as_units` stays off for this fund. The rows stay classed as loans.
- Consequence: rule X11 keeps firing on this fund (9 fund-quarters now, more from 2026-06-30 when
  the filing labels many more CLO tranches this way). They need a disposition ('as filed: the
  filer reports a face amount in the unit column and no principal'), not yet recorded.
- Also confirmed the same day: BCRED Pigments Services 2023-06-30 has no principal or share-count
  fact on either context in the filing itself (tags: spread, rate, cost, fair value, percent) and
  none on the page. As filed.

### D-152 Two dispositions recorded for rule X11 (owner, 2026-10-13: "yes, record both")

Store `data/overrides/finding_dispositions/owner_2026-10-13.json`.
- **DS-X11-1918712, Ares Strategic Income, as filed.** Coupon-bearing tranches reported in the
  Shares/Units column with no principal fact (D-151). Eight quarters listed. It carries forward
  from 2026-09-30 through a new check, `no_principal_in_source` (`pipeline/disposition_validity.py`,
  test added): every flagged row must still carry a unit count and no principal fact, so the
  entry stops applying the quarter the filer starts tagging a par or a row arrives with neither.
  **2026-03-31 is not covered:** one flagged row there (JPMMT 2026-ACES1, a residential
  mortgage-backed security, 75M) has neither a count nor a par and has not been read.
- **DS-X11-1803498-PIGMENTS, BCRED 2023-06-30, as filed.** Two Pigments Services loans with no
  par on the page and no principal or share-count fact in the filing. One quarter, no
  carry-forward (the next filing tags the par).
- Ledger: Ares Strategic Income X11 9 to 1; BCRED X11 2 to 1 (the New Mountain CLO 6 note with
  zero cost at 2024-12-31 is a different row and stays). Top ten about 26 outstanding, pieced
  together from several sandboxes; one build of the ten is still owed before quoting it.

### D-153 Top ten: the remaining findings worked through, one build of the ten (sandboxes `t10a`, `ap2`, with 2026-06-30)

Owner, 2026-10-13: "fix the remaining 35". About 26 were left after D-152. Each row was read on the
printed schedule before a change. Result: top ten 3 outstanding of 517 findings, all three waiting
for the owner. Published equals filed within 0.5M in 139 of 141 fund-quarters (Ares Strategic
Income 2025-03-31 +2.5M and Golub 2023-12-31 -3.5M, not re-read in this round); every quarter has
a filed total.

**Fixed**
- **Apollo: par tagged as a second cost fact in a foreign unit** (new setting
  `source_encodings.cost_in_two_units: ["foreign_is_par"]`, module `pipeline/cost_in_two_units.py`,
  Apollo only). JOA Joker 2025-09-30 and 2025-12-31 and Waystone delayed draw 2026-06-30 carry
  InvestmentOwnedAtCost twice (EUR 126,725,000 and USD 132,847,000; page 'EUR 126,725 132,847
  147,810') and no principal fact. The extractor keeps the first fact, so the euro par was
  published as the dollar cost. A context with exactly one dollar and one foreign cost fact now
  publishes the dollar fact as cost and the foreign one as par in that currency. Five such contexts
  in all Apollo filings, none with a principal fact. The re-verifier re-reads the fact of the unit
  named in the event.
- **Par declared from the page** (`untagged_values`, which now takes an optional currency code for
  a principal): Apollo SumUp 2024-06-30 (EUR 40,000), Version 1 2025-12-31 (GBP 6,559), Rise and
  Brill revolver 2024-09-30 (356, cost 330); Ares Sunrun Xanadu 2022-09-30 (71.3M par and cost;
  first lien cost 0.4M); BCRED New Mountain CLO 6 2024-12-31 (1,875,000); Sixth Street LP Price Fx
  2024-12-31 (EUR 910). Lines quoted in `scratch/2026-10-13_left/apply_wrappers.py`.
- **Ares Viant 2024-03-31:** the flagged row was the company's total line (0.5 / 0.5) tagged on a
  member spelled like a position and published beside the two positions it sums. Excluded
  (`agent_investigate_rules/1287750/exclude_viant_issuer_total_2024q1.json`).
- **Ares Murchison 2024-12-31:** 41,000 preferred units (cost dash, value 6.7M) tagged under the
  loan member; reclassed by row correction.
- **Oaktree industry** (new setting `source_encodings.industry_columns`, Oaktree only): the fund
  prints each row's industry in a column; the page reader took nothing. Now 100 pct of rows in 11
  of 14 quarters carry the printed industry and a GICS label (before: none, except 48 rows at
  2023-06-30 whose members carried it).

**Found while reading, no rule had flagged it**
- Apollo Version 1 euro term loan 2025-12-31 published the sterling loan's par: its context carries
  two principal facts (GBP 6,559,000 and EUR 4,029,000) and the first won. Corrected by row
  correction to EUR 4,029,000; dollar amount at the build's own reference rate for that date
  (1.1736). One such context in all Apollo filings.

**Closed on a reason the owner had accepted** (`finding_dispositions/accepted_reasons_2026-10-13.json`)
- Ares 2007-3R subordinated notes, six quarters: 20,000,000 in the Shares/Units column, no
  principal (reason of D-151). Carries forward through `no_principal_in_source`.
- Sixth Street LP Galileo 2023-06-30 and Cordance 2025-06-30, 2025-09-30: no par printed, no
  principal fact (reason of the Pigments entry, D-152).
- Blue Owl PP03, four quarters: current-period rows whose count and values equal the prior
  period's (reason of DS-024 and of the Oaktree entry, D-146).

**Left for the owner** (`finding_dispositions_proposed/top10_2026-10-13.json`)
1. Blue Owl 2024-12-31 coverage drop: about 220 commitment-table rows tagged from that filing; the
   table prints no cost, maturity, industry or percent.
2. Blue Owl 2025-03-31 coverage drop: no percent of net assets printed or tagged on position rows
   from that filing; the recomputed percent is published.
3. Ares Strategic Income 2026-03-31: JPMMT 2026-ACES1 prints 1,405,613,866 in the unit column and
   tags it with the filer's percent-of-shares concept, so the accepted entry's check (which needs
   a share-count fact) does not cover the quarter.

**Mistakes of mine in this round**
- The first build showed four new Apollo findings caused by the fix itself: the cost event recorded
  the euro figure as the declared raw value (re-verifier: anchor_stale, three rows), and the
  Version 1 correction withdrew the dollar par (FX01). Both corrected; Apollo rebuilt alone (`ap2`:
  64 findings, 0 outstanding).
- The count of 35 quoted to the owner earlier that day was read from ledgers written before D-152.

Not measured: the two new settings and the currency suffix are wrapper-switched and touch no other
fund by construction, but no fund outside the ten was rebuilt. "3 outstanding" is not "data
correct": the Version 1 par shows what no rule sees.

### D-154 MSD Investment Corp. cleared through the fund-clearing skill, first run (sandbox `msdxa`)

Owner, 2026-10-13: "do it" (build the skill), then a first run on fund 11. One agent owned the
fund; the orchestrator ran the gate (`scripts/v05_evidence/fund_gate.py`). Verdict PASS on the
first round: stages clean, 13 of 13 quarters tie, every changed column declared (principal on 2
rows, unit count on 1), 49 quotes found in the filings, no forbidden file touched.

- **Fixed:** Mattress Firm par at 2023-06-30 and 2023-09-30 declared from the page (1,326 and
  1,322; the filer tagged it on another context); Metropolis warrant at 2024-09-30 published 6,314
  units where the tag and the page say 4 (row correction; no rule had flagged it).
- **Ledger:** 74 findings, 39 outstanding (41 before), all 39 with a proposal in
  `finding_dispositions_proposed/fund_0001849894.json` (12 entries). None accepted.
- **Agent's correction of the earlier reading (D-099):** the 'Par Amount / Shares' figure on the
  PIK preferred rows is a dollar amount that grows at the PIK rate, not a unit count;
  `units_tagged_as_par` would publish wrong values and was not used.
- **Seen on the page, no rule:** the shared unit-scale normaliser compares all rows of one issuer
  and rescaled the warrant count (and Protective Industrial preferred at 2023-12-31: 31,597
  published as 31). Other funds not measured. Two declared pars carry the source label
  `xbrl_field` although they come from the page.
- **Not checked by the agent:** four findings carry an earlier reviewer's 'real error' verdict with
  no detail; the A01 subtotal members were taken from the check's output; non-accrual flags,
  labels and position identity were not re-read. One build only.
- What the run showed about the skill: the agent ran the gate itself before reporting (allowed,
  but it lets an agent work to the gate); it killed a stray Python process by image name, which
  would have killed another session's build. Both go into the brief.

"39 with a proposal" is not "data correct".

### D-155 Two rule repairs, by owner ruling (sandbox `owlr1`)

Owner, 2026-10-13: "do it" to both repairs proposed after the reversal of D-153's self-accepted
dispositions.

- **PP03 (prior-period row)** found a row's period by matching its published values against the
  source rows. A published value that differs from the source value (a unit count rescaled to the
  scale of earlier filings) then matched only the prior-period fact. The rule now takes the period
  of the row's own context where the build recorded one (`src_context_id`), and matches on values
  only where it did not. `pipeline/position_purity.py`, one test with the Blue Owl shape and its
  two counter-cases.
- **field_coverage_drop** counted every published row for cost, maturity, industry and percent of
  net assets. It now counts rows with a positive fair value for every field, as it already did for
  principal and rate. A filer that starts tagging its commitments table (Blue Owl from 2024-12-31,
  about 220 rows a quarter with a value of zero or below) no longer reads as a drop on the
  positions. Not seen any more: a field lost on undrawn lines alone.
  `scripts/shadow_identity_engine.py`, one test.
- **Measured on Blue Owl with 2026-06-30** (`owlr1` against `t10a`): outstanding 6 to 1; the four
  PP03 findings and the 2024-12-31 coverage finding are gone; no new finding; no quarter stopped
  tying. The one left is the 2025-03-31 percent-of-net-assets drop, which is real (the filer
  stopped printing it) and stays a proposal. Eight rows lost their GICS label between the two
  builds; cause not traced (the fund was built alone this time).
- Not measured: any other fund. Both rules are shared.
- Top ten after this: 11 outstanding, all with a proposal, in four groups (Ares 2007-3R x6, Sixth
  Street LP no par printed x3, Blue Owl percent x1, Ares Strategic Income JPMMT x1).
