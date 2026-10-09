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
