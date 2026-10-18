# v0.5 candidate rules, measured on the accepted sandboxes (2026-10-17, revised 2026-10-18)

Revision 2026-10-18: the rules were changed after the independent false-alarm review (`v05_rule_candidates_falsealarm_2026-10-18.md`) and the owner's rulings (D-207): rule 1 passes a name printed as a name elsewhere in the filing and a trailing legal-form difference, and raises no page flags in a fund-quarter that is 90 pct or more untested (blind-spot table below); rule 2 strips the issuer name, passes a count printed on the row, and reports exact x1000 cases as `units_scale_unclear`; rule 3 raises on the printed row only (member text alone is `pik_member_text_only`) and passes a tag rounded to fewer decimals; rule 4 finds below 0.80, warns below 0.90, and exempts funds whose filings print no industry; rule 5 keeps the text kinds only. Counts below are this run; the first run's are beside them.

Owner, 2026-10-17: "do it" -- build the five candidate rules and measure them; do NOT switch them on. Code: `pipeline/candidate_rules.py` (not imported by the build, ledger, shadow engines, quarter pass or gate). Script: `scripts/v05_evidence/measure_candidate_rules.py`. Inputs: each fund's accepted sandbox in `docs/investigations/v05_readings/accepted_sandboxes.json`, published basis (no `underlying_schedule` rows). Page access: `printed_row` from that sandbox's `bdc_ixbrl_field_status` (current period, member printed once).

Files: `v05_rule_candidates_2026-10-17.csv` (rule x fund), `v05_rule_candidates_2026-10-17_rows.csv` (every flagged row), `v05_rule_candidates_2026-10-17_industry_coverage.csv` (rule 4, with level), `v05_rule_candidates_2026-10-17_rule1_blind_spots.csv` (rule 1, per fund-quarter).

Funds measured: 52; published rows: 257293; rows whose printed row is known: 246425 (95.8 pct). Funds where the page reader is (almost) never joined fall back to member text and shape tests: 0002008748 Lord Abbett Private Credit Fund (139 of 705).

A clean result is not 'data correct': these rules see only what the page reader joined and the shapes coded.

## Totals

Findings are the kinds the review and D-207 treat as errors (`candidate_rules.FINDING_KINDS`); weaker kinds (`units_scale_unclear`, `pik_member_text_only`, `preferred_heading_only`) are counted apart. Old = commit 6751318 (51 funds, all kinds then emitted); 10-18 = commit ddc0e92 (first revision, 52 funds); new = this run (2026-10-19 follow-ups: rule 1 near-spelling pass, rule 5 heading-only to the weaker kind). Not counted here: the ledger also leaves out rule-1 shape flags in untested fund-quarters (`ledger_rows`).

| rule | old rows | 10-18 rows | new rows (findings) | weaker kinds | old FQ | new FQ | old funds | new funds | old FV (M) | new FV (M) | kinds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| issuer_name_differs_from_page | 6537 | 5759 | 5934 | 0 | 370 | 321 | 48 | 47 | 217529.3 | 211428.4 | not_the_printed_name:5771; spacing_only:116; begins_with_section_word:23; equals_industry_label:10; begins_with_industry_label:8; holds_category_path:6 |
| unit_count_differs_from_row_text | 459 | 416 | 416 | 34 | 140 | 126 | 27 | 21 | 5981.8 | 5895.9 | proxy_count_not_on_row:384; units_scale_unclear:34; labelled_count_differs:19; labelled_count_not_published:13 |
| pik_printed_not_published | 245 | 221 | 221 | 22 | 88 | 81 | 22 | 22 | 3271.5 | 3158.1 | pik_printed_not_published:192; pik_value_mismatch:29; pik_member_text_only:22 |
| industry_not_published | 4676 | 4461 | 4461 | 0 | 57 | 59 | 13 | 13 | 40291.7 | 39264.9 | no_industry_at_all:4362; filer_industry_not_mapped:99 |
| preferred_published_as_common | 546 | 147 | 47 | 100 | 122 | 30 | 18 | 8 | 5861.4 | 1383.4 | preferred_heading_only:100; text_says_preferred:24; text_and_rate:23 |

## issuer_name_differs_from_page

**Overlap with existing rules.** Partial. Oracle I09 flags a fund-quarter where more than 5 pct of issuer names equal a GICS sub-industry label (aggregate; misses isolated rows, the filer's own labels and any name that is merely wrong). The fund gate's check_names (scripts/v05_evidence/fund_gate.py, not a ledger rule) looks for instrument words, row numbers, holder labels and a leading industry, above 1 pct of a fund's rows. Neither compares the name with the printed row, so the observed member-spelling cases (Covetrus as 'CVET Midco 2', NextCar, 'Global Solutions' for Continuum Global Solutions) pass both.

**Blind spots (part of the rule's result).** Of 257293 published rows with an issuer name, 58612 (22.8 pct) could not be tested on the page (10868 with no printed row, 47744 with a printed row but no name cell). 60 fund-quarters are 90 pct or more untested and raise no page-basis flags (shape flags still run). A clean rule-1 result there means 'not looked at'. Funds with the most untested fund-quarters:

| cik | fund | fund-quarters | suppressed | blind share (rows) |
|---|---|---:|---:|---:|
| 0001925531 | New Mountain Guardian IV BDC, L.L.C. | 14 | 14 | 0.98 |
| 0001766037 | NMF SLF I, Inc. | 14 | 14 | 0.97 |
| 0001950803 | Stepstone Private Credit Fund LLC | 12 | 11 | 0.95 |
| 0002037804 | New Mountain Private Credit Fund | 7 | 7 | 0.96 |
| 0002008748 | Lord Abbett Private Credit Fund | 8 | 7 | 0.80 |
| 0001772704 | Goldman Sachs Private Middle Market Credit II... | 14 | 2 | 0.19 |
| 0001572694 | Goldman Sachs BDC, Inc. | 14 | 2 | 0.16 |
| 0001634452 | AB Private Credit Investors Corp | 14 | 2 | 0.13 |
| 0001920145 | Goldman Sachs Private Credit Corp. | 13 | 1 | 0.04 |
| 0001287750 | ARES CAPITAL CORP | 16 | 0 | 0.59 |
| 0001786108 | Trinity Capital Inc. | 14 | 0 | 0.54 |
| 0001278752 | MidCap Financial Investment Corp | 14 | 0 | 0.52 |
| 0001849894 | MSD Investment Corp. | 13 | 0 | 0.43 |
| 0001837532 | Apollo Debt Solutions BDC | 14 | 0 | 0.41 |
| 0001918712 | ARES STRATEGIC INCOME FUND | 14 | 0 | 0.29 |

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 4177 | 14 | 183211.0 | not_the_printed_name:4174; spacing_only:2; begins_with_section_word:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 122 | 14 | 8756.2 | not_the_printed_name:113; spacing_only:7; begins_with_section_word:2 |
| 0001287750 | ARES CAPITAL CORP | rg1b | 80 | 14 | 2978.7 | not_the_printed_name:73; holds_category_path:6; spacing_only:1 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 206 | 10 | 2807.9 | not_the_printed_name:206 |
| 0001920145 | Goldman Sachs Private Credit Corp. | rg1b | 148 | 12 | 2139.2 | not_the_printed_name:145; spacing_only:2; begins_with_section_word:1 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 17 | 5 | 1695.1 | not_the_printed_name:15; spacing_only:2 |
| 0001872371 | Oaktree Strategic Credit Fund | rg1b | 83 | 6 | 986.3 | not_the_printed_name:64; begins_with_section_word:11; spacing_only:8 |
| 0001965934 | Overland Advantage | ovye | 6 | 6 | 879.0 | equals_industry_label:4; not_the_printed_name:2 |
| 0001825384 | Stone Point Credit Corp | stxf | 50 | 12 | 743.9 | not_the_printed_name:46; spacing_only:4 |
| 0001572694 | Goldman Sachs BDC, Inc. | gsxf | 63 | 12 | 600.8 | not_the_printed_name:52; begins_with_section_word:7; spacing_only:4 |
| 0001950976 | 26North BDC, Inc. | tnxc | 17 | 8 | 518.0 | not_the_printed_name:15; spacing_only:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 34 | 12 | 517.2 | not_the_printed_name:34 |
| 0002031750 | Ares Core Infrastructure Fund | acxb | 2 | 2 | 454.5 | not_the_printed_name:2 |
| 0001742313 | Monroe Capital Income Plus Corp | rg2 | 105 | 9 | 452.5 | not_the_printed_name:76; spacing_only:29 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 127 | 9 | 437.4 | not_the_printed_name:118; spacing_only:4; begins_with_industry_label:3; equals_industry_label:1; begins_with_section_word:1 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 61 | 14 | 431.4 | not_the_printed_name:53; spacing_only:8 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 9 | 4 | 382.1 | not_the_printed_name:9 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 78 | 14 | 373.8 | not_the_printed_name:63; spacing_only:15 |
| 0001772704 | Goldman Sachs Private Middle Market Credit II... | gpyf | 58 | 6 | 354.8 | not_the_printed_name:58 |
| 0001899017 | Bain Capital Private Credit | bnxd | 38 | 11 | 319.0 | not_the_printed_name:34; spacing_only:4 |
| 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. | viya | 8 | 5 | 294.1 | not_the_printed_name:8 |
| 0001976336 | Antares Private Credit Fund | atxc | 55 | 7 | 215.1 | not_the_printed_name:50; begins_with_industry_label:4; equals_industry_label:1 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 31 | 9 | 185.9 | not_the_printed_name:31 |
| 0001859919 | Barings Private Credit Corp | rg2 | 59 | 8 | 178.7 | not_the_printed_name:54; spacing_only:4; begins_with_industry_label:1 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 22 | 3 | 173.4 | not_the_printed_name:22 |
| 0001916099 | Diameter Credit Co | dixc | 12 | 8 | 170.4 | not_the_printed_name:12 |
| 0001920453 | Fidelity Private Credit Fund | fpxg | 33 | 11 | 150.0 | not_the_printed_name:33 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 38 | 7 | 134.0 | not_the_printed_name:36; spacing_only:2 |
| 0001902649 | BlackRock Private Credit Fund | bpxh | 60 | 14 | 117.7 | not_the_printed_name:54; spacing_only:6 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 49 | 7 | 115.3 | not_the_printed_name:37; spacing_only:12 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 6 | 4 | 99.4 | not_the_printed_name:6 |
| 0001869453 | Blue Owl Technology Income Corp. | rg2 | 9 | 4 | 97.6 | not_the_printed_name:9 |
| 0001901164 | T. Rowe Price OHA Select Private Credit Fund | trxd | 11 | 5 | 94.2 | not_the_printed_name:11 |
| 0001849894 | MSD Investment Corp. | rg2 | 2 | 2 | 66.8 | not_the_printed_name:2 |
| 0001959604 | Jefferies Credit Partners BDC Inc. | jcxd | 17 | 6 | 65.3 | not_the_printed_name:17 |
| 0001950803 | Stepstone Private Credit Fund LLC | spxf | 1 | 1 | 48.3 | equals_industry_label:1 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 4 | 4 | 43.4 | not_the_printed_name:4 |
| 0001899996 | Fidelity Private Credit Co LLC | fcxe | 2 | 1 | 40.9 | not_the_printed_name:2 |
| 0002037804 | New Mountain Private Credit Fund | npxd | 1 | 1 | 26.5 | equals_industry_label:1 |
| 0002012139 | Fortress Private Lending Fund | foxd | 3 | 2 | 18.5 | not_the_printed_name:3 |
| 0001911066 | Nuveen Churchill Private Capital Income Fund | ncxf | 1 | 1 | 16.4 | not_the_printed_name:1 |
| 0001885968 | T Series BDC LLC | tsxd | 9 | 4 | 16.0 | not_the_printed_name:9 |
| 0001786108 | Trinity Capital Inc. | tcxe | 5 | 5 | 15.0 | not_the_printed_name:5 |
| 0001975736 | KKR FS Income Trust Select | ksxf | 8 | 3 | 4.6 | not_the_printed_name:8 |
| 0001901612 | Golub Capital BDC 4, Inc. | g4xc | 4 | 3 | 1.7 | not_the_printed_name:4 |
| 0002008748 | Lord Abbett Private Credit Fund | layf | 2 | 1 | 0.7 | equals_industry_label:2 |
| 0001913724 | TPG Twin Brook Capital Income Fund | rg2 | 1 | 1 | -0.1 | not_the_printed_name:1 |

**Read of the samples below (agent; not a disposition).** 9 of 10 real: 8 carry the member's group name in front of the legal name (Apollo Debt Solutions 'Delivery Hero Delivery Hero Finco Germany GmbH', 'Golden Hippo Altern Marketing, LLC'; Apollo is 4,177 of the 5,759 rows), 1 a heading residue (Sixth Street 'and Consumer Products Rapid Data GmbH'). 1 cosmetic: Crescent 'Bankers Toolbox' for the printed 'Banker's Toolbox' (kind spacing_only; an apostrophe, not a build error). The New Mountain industry-cell leaks are gone with the blind-quarter suppression. (Read on the 2026-10-18 run; the 2026-10-19 near-spelling restriction adds 175 rows, the Wildcat shape and misjoined printed rows that the broad 'printed elsewhere' pass had hidden; not re-sampled.)

Sample of 10 flagged rows, seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | Crescent Capital BDC, Inc. 2023-06-30 | not_the_printed_name / page | MRI Software LLC | 1,891,000 | MRI Software LLC | New Era Technology, Inc. | New Era Technology, Inc. / Unitranche First Lien Delayed Draw Term Loan / S + 625 (100 Floor) / 11.75% / 10/2026 / 1,953 / 1,931 / 0.3 / 1,891 |
| 2 | Apollo Debt Solutions BDC 2023-09-30 | not_the_printed_name / page | Accelerate360 Accelerate360 Holdings, LLC | 71,671,000 | Accelerate360 Accelerate360 Holdings, LLC | Accelerate360 Holdings, LLC | Accelerate360 Holdings, LLC / First Lien Secured Debt / S+626, 1.00% Floor / 2/11/2027 / $ / 71,315 / $ / 71,315 / $ / 71,671 / (4)(9)(17) |
| 3 | Apollo Debt Solutions BDC 2024-06-30 | not_the_printed_name / page | Roaring Fork III-B Roaring Fork III-B, LLC | 1,153,000 | Roaring Fork III-B Roaring Fork III-B, LLC | Roaring Fork III-B, LLC | Roaring Fork III-B, LLC / First Lien Secured Debt - Term Loan / S+540, 0.00% Floor / 7/16/2026 / $ / 1,153 / $ / 1,153 / $ / 1,153 / (4)(8)(9)(15) |
| 4 | Apollo Debt Solutions BDC 2024-12-31 | not_the_printed_name / page | ArcLight AL GCX Holdings, LLC | 5,040,000 | ArcLight AL GCX Holdings, LLC | AL GCX Holdings, LLC | AL GCX Holdings, LLC / First Lien Secured Debt - Term Loan / S+275, 0.50% Floor / 5/17/2029 / $ / 5,000 / $ / 5,024 / $ / 5,040 / (14) |
| 5 | Apollo Debt Solutions BDC 2025-12-31 | not_the_printed_name / page | Howden Group HIG Finance 2 Limited | 9,988,000 | Howden Group HIG Finance 2 Limited | HIG Finance 2 Limited | HIG Finance 2 Limited / First Lien Secured Debt - Term Loan / S+275, 0.50% Floor / 4/18/2030 / 9,949 / 9,904 / 9,988 / (8)(16) |
| 6 | Apollo Debt Solutions BDC 2025-12-31 | not_the_printed_name / page | Clarience Technologies Truck-Lite Co., LLC | 192,651,000 | Clarience Technologies Truck-Lite Co., LLC | Truck-Lite Co., LLC | Truck-Lite Co., LLC / First Lien Secured Debt - Term Loan / S+475, 0.75% Floor / 2/13/2032 / $ / 194,499 / $ / 193,755 / $ / 192,651 / (4)(15) |
| 7 | Apollo Debt Solutions BDC 2026-03-31 | not_the_printed_name / page | Dynagrid Megavolt Borrower, LLC | 18,470,000 | Dynagrid Megavolt Borrower, LLC | Megavolt Borrower, LLC | Megavolt Borrower, LLC / First Lien Secured Debt - Term Loan / S+475, 1.00% Floor / 02/13/2032 / 18,609 / 18,283 / 18,470 / (4)(16) |
| 8 | Apollo Debt Solutions BDC 2026-03-31 | not_the_printed_name / page | Enverus Edition Holdings, Inc. | 307,561,000 | Enverus Edition Holdings, Inc. | Edition Holdings, Inc. | Edition Holdings, Inc. / First Lien Secured Debt - Term Loan / S+450, 0.75% Floor / 12/20/2032 / 310,668 / 309,836 / 307,561 / (4)(15) |
| 9 | Apollo Debt Solutions BDC 2026-03-31 | not_the_printed_name / page | Walter's WH BorrowerCo, LLC | 19,479,000 | Walter's WH BorrowerCo, LLC | WH BorrowerCo, LLC | WH BorrowerCo, LLC / First Lien Secured Debt - Term Loan / S+500, 1.00% Floor / 08/02/2030 / 20,238 / 20,002 / 19,479 / (4)(9)(16) |
| 10 | Goldman Sachs Private Credit... 2025-06-30 | not_the_printed_name / page | Madison IAQ LLC Commercial Services & Supplies | 14,407,000 | Madison IAQ LLC Commercial Services & Supplies | Madison IAQ LLC | Madison IAQ LLC / Commercial Services & Supplies / 6.76% / S + 2.50% / 06/21/28 / 14,404 / 14,439 / 14,407 |

## unit_count_differs_from_row_text

**Overlap with existing rules.** None on value. Oracle C04 requires 70 pct of a fund-quarter's equity rows to carry any unit count (presence only); F11 checks the sign. field_coverage_drop ('unit count on equity') looks at the share carrying a count against the prior quarter. A wrong count published by the shared normaliser satisfies all three.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001287750 | ARES CAPITAL CORP | rg1b | 188 | 16 | 4418.7 | proxy_count_not_on_row:186; labelled_count_not_published:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 45 | 14 | 1053.6 | proxy_count_not_on_row:37; units_scale_unclear:8 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 60 | 16 | 195.1 | proxy_count_not_on_row:60 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 22 | 9 | 66.2 | proxy_count_not_on_row:22 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 33 | 14 | 60.0 | proxy_count_not_on_row:33 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 25 | 9 | 55.3 | units_scale_unclear:16; proxy_count_not_on_row:9 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 8 | 7 | 31.5 | labelled_count_differs:6; labelled_count_not_published:2 |
| 0001849894 | MSD Investment Corp. | rg2 | 1 | 1 | 27.6 | proxy_count_not_on_row:1 |
| 0001869453 | Blue Owl Technology Income Corp. | rg2 | 1 | 1 | 14.7 | units_scale_unclear:1 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 6 | 3 | 10.4 | proxy_count_not_on_row:6 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 3 | 3 | 8.5 | proxy_count_not_on_row:3 |
| 0001872371 | Oaktree Strategic Credit Fund | rg1b | 4 | 2 | 6.7 | proxy_count_not_on_row:4 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 7 | 3 | 6.2 | proxy_count_not_on_row:4; units_scale_unclear:3 |
| 0001976336 | Antares Private Credit Fund | atxc | 1 | 1 | 5.4 | proxy_count_not_on_row:1 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 2 | 1 | 4.8 | labelled_count_not_published:2 |
| 0001899017 | Bain Capital Private Credit | bnxd | 1 | 1 | 3.9 | units_scale_unclear:1 |
| 0001950976 | 26North BDC, Inc. | tnxc | 3 | 3 | 1.1 | units_scale_unclear:3 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 13 | 10 | 1.1 | proxy_count_not_on_row:13 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 2 | 2 | 1.0 | proxy_count_not_on_row:2 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 1 | 1 | 1.0 | proxy_count_not_on_row:1 |
| 0001859919 | Barings Private Credit Corp | rg2 | 2 | 2 | 0.9 | labelled_count_differs:2 |
| 0001920145 | Goldman Sachs Private Credit Corp. | rg1b | 2 | 2 | 0.7 | proxy_count_not_on_row:2 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 11 | 8 | 0.6 | labelled_count_not_published:7; labelled_count_differs:4 |
| 0001885968 | T Series BDC LLC | tsxd | 1 | 1 | 0.3 | units_scale_unclear:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 7 | 7 | 0.1 | labelled_count_differs:7 |
| 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. | viya | 1 | 1 | 0.0 | units_scale_unclear:1 |

**Read of the samples below (agent; not a disposition).** Finding kinds: 9 of 10 real (Ares AthenaHealth 198,505 for 10,487,951; Carlyle Talon 1,018,000 for 145,631; ASIF Mustang 883 for 883,420; BCRED Point Broadband, Zoro, Jupiter), 1 unclear (BCRED GTCR/Jupiter 'Blocker Note', a note classed equity whose 115,036 is a par). units_scale_unclear holds HPS-type rows as asked, but the same shape also covers rows the review called real (26North FH DMI 400,429,000 for 400,429) and Blue Owl rows (Insight CP 989,000 for 989): read it as 'x1000, scale not on the row', not as 'probably fine'.

Sample of 10 flagged rows (finding kinds), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2024-03-31 | proxy_count_not_on_row / page | PerkinElmer U.S. LLC and NM Polaris Co-Invest, L.P... | 13,400,000 | 34832.0 (derived_proxy) | figures: 3.0; 2023.0; 0.62; 9.9; 13.4; 2.0 | Limited partnership interests / 03/2023 / 0.62% / 9.9 / 13.4 / (2) |
| 2 | ARES CAPITAL CORP 2025-09-30 | proxy_count_not_on_row / page | AthenaHealth Group Inc., Minerva Holdco, Inc. and ... | 14,800,000 | 198505.0 (derived_proxy) | figures: 2.0; 2022.0; 10487951.0; 10.5; 14.8; 2.0 | Class A units / 02/2022 / 10,487,951 / 10.5 / 14.8 / (2) |
| 3 | Crescent Capital BDC, Inc. 2023-12-31 | proxy_count_not_on_row / page | Patriot Acquisition Topco S.A.R.L | 56,000 | 1148.0 (derived_proxy) | figures: 11.0; 15809.0; 42.0; 0.0; 56.0 | Patriot Acquisition Topco S.A.R.L (11) / Common Stock / 15,809 / 42 / 0.0 / 56 |
| 4 | Carlyle Credit Solutions, In... 2023-03-31 | proxy_count_not_on_row / page | Talon MidCo 1 Limited | 1,725,000 | 1018000.0 (derived_proxy) | figures: 7.0; 145631.0; 1456.0; 1725.0; 0.15 | Talon MidCo 1 Limited / ^ / (7) / Software / 8/17/2022 / 145,631 / 1,456 / 1,725 / 0.15 |
| 5 | Blackstone Private Credit Fu... 2024-09-30 | proxy_count_not_on_row / page | Point Broadband Holdings, LLC | 591,000 | 2766.0 (derived_proxy) | figures: 4.0; 147380.0; 420.0; 591.0; 0.0 | Point Broadband Holdings, LLC - Class Additional B Common Units / (4) / 3/24/2022 / 147,380 / 420 / 591 / 0.00 |
| 6 | Blackstone Private Credit Fu... 2025-06-30 | proxy_count_not_on_row / page | Zoro | 13,155,000 | 44535.0 (derived_proxy) | figures: 4.0; 1195880.0; 11959.0; 13155.0; 0.03 | Zoro - Common Equity / (4) / 11/22/2022 / 1,195,880 / 11,959 / 13,155 / 0.03 |
| 7 | Blackstone Private Credit Fu... 2025-09-30 | proxy_count_not_on_row / page | GTCR/Jupiter Blocker, LLC | 115,000 | 749.0 (derived_proxy) | figures: 4.0; 115036.0; 115.0; 115.0; 0.0 | GTCR/Jupiter Blocker, LLC - Blocker Note / (4) / 12/2/2024 / 115,036 / 115 / 115 / 0.00 |
| 8 | Blackstone Private Credit Fu... 2025-09-30 | proxy_count_not_on_row / page | Point Broadband Holdings, LLC | 2,482,000 | 2766.0 (derived_proxy) | figures: 4.0; 685760.0; 1955.0; 2482.0; 0.01 | Point Broadband Holdings, LLC - Class B Common Units / (4) / 10/1/2021 / 685,760 / 1,955 / 2,482 / 0.01 |
| 9 | Blackstone Private Credit Fu... 2026-03-31 | proxy_count_not_on_row / page | Jupiter Ultimate Holdings, LLC | 5,288,000 | 5082.0 (derived_proxy) | figures: 4.0; 5084731.0; 4035.0; 5288.0; 0.01 | Jupiter Ultimate Holdings, LLC - Class C Common Units / (4) / 11/8/2024 / 5,084,731 / 4,035 / 5,288 / 0.01 |
| 10 | ARES STRATEGIC INCOME FUND 2025-12-31 | proxy_count_not_on_row / page | Mustang Prospects Holdco, LLC, Mustang Prospects P... | 353,700 | 883.0 (derived_proxy) | figures: 9.0; 2024.0; 883420.0; 380.1; 353.7; 13.0 | Class B common units / 09/2024 / 883,420 / 380.1 / 353.7 / (13) |

Sample of 10 flagged rows (weaker kind units_scale_unclear), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | Blue Owl Credit Income Corp. 2024-09-30 | units_scale_unclear / page | BEHP Co-Investor II, L.P. | 1,297,000 | 1269969.0 (derived_proxy) | figures: 23.0; 24.0; 26.0; 1270.0; 1042.0; 1297.0; 0.0 | BEHP Co-Investor II, L.P.(23)(24)(26) / LP Interest / N/A / N/A / 1,270 / 1,042 / 1,297 / 0.0 / % |
| 2 | Blue Owl Credit Income Corp. 2025-03-31 | units_scale_unclear / page | Insight CP (Blocker) Holdings, L.P. (dba CivicPlus... | 1,239,000 | 989000.0 (derived_proxy) | figures: 22.0; 23.0; 25.0; 989.0; 989.0; 1239.0 | Insight CP (Blocker) Holdings, L.P. (dba CivicPlus, LLC)(22)(23)(25) / LP Interest / N/A / N/A / 989 / 989 / 1,239 |
| 3 | HPS Corporate Lending Fund 2024-03-31 | units_scale_unclear / page | SLF V AD1 Holdings, LLC | 9,831,000 | 10101000.0 (derived_proxy) | figures: 4.0; 18.0; 19.0; 10101.0; 9892.0; 9831.0 | SLF V AD1 Holdings, LLC (4)(18)(19) / 10,101 / 9,892 / 9,831 |
| 4 | HPS Corporate Lending Fund 2025-06-30 | units_scale_unclear / page | Racing Point UK Holdings Limited | 1,152,000 | 168000.0 (derived_proxy) | figures: 4.0; 5.0; 23.0; 168.0; 1008.0; 1152.0 | Racing Point UK Holdings Limited (4)(5)(23) - Ordinary Shares / 168 / 1,008 / 1,152 |
| 5 | HPS Corporate Lending Fund 2025-06-30 | units_scale_unclear / page | Southern Graphics Holdings LLC | 3,663,000 | 274000.0 (derived_proxy) | figures: 4.0; 21.0; 23.0; 274.0; 2333.0; 3663.0 | Southern Graphics Holdings LLC (4)(21)(23) - Class A Units / 274 / 2,333 / 3,663 |
| 6 | HPS Corporate Lending Fund 2025-12-31 | units_scale_unclear / page | Wash & Wax Group LP | 6,991,000 | 6312000.0 (derived_proxy) | figures: 4.0; 20.0; 22.0; 6312.0; 8547.0; 6991.0 | Wash & Wax Group LP (4)(20)(22) - Class A Common Units / 6,312 / 8,547 / 6,991 |
| 7 | HPS Corporate Lending Fund 2025-12-31 | units_scale_unclear / page | The ONE Group Hospitality, Inc. | 21,000 | 11911000.0 (derived_proxy) | figures: 22.0; 2.0; 11911.0; 61.0; 21.0; 2.0 | The ONE Group Hospitality, Inc. (22) - A-2 Warrants / 11,911 / 61 / 21 |
| 8 | Blue Owl Technology Income C... 2025-12-31 | units_scale_unclear / page | ModMed Software Midco Holdings, Inc. (dba ModMed) | 14,727,000 | 13733060.0 (derived_proxy) | figures: 3.0; 4.0; 6.0; 30.0; 13.0; 13733.0; 14608.0; 14727.... | ModMed Software Midco Holdings, Inc. (dba ModMed)(3)(4)(6)(30) / Series A Preferred Units / N/A / 13.00% / N/A / 13,733 / 14,608 / 14,727 |
| 9 | 26North BDC, Inc. 2025-03-31 | units_scale_unclear / page | FH DMI Buyer, Inc | 348,000 | 400429000.0 (derived_proxy) | figures: 400429.0; 400.0; 348.0; 0.07 | FH DMI Buyer Inc / Common Stock / Health Care Equipment & Supplies / 10/11/2024 / 400,429 / 400 / 348 / 0.07 / % |
| 10 | 26North BDC, Inc. 2025-06-30 | units_scale_unclear / page | FH DMI Buyer, Inc | 372,000 | 400429000.0 (derived_proxy) | figures: 10.0; 400429.0; 400.0; 372.0; 0.08 | FH DMI Buyer Inc (10) / Common Stock / Health Care Equipment & Supplies / 10/11/2024 / 400,429 / 400 / 372 / 0.08 / % |

## pik_printed_not_published

**Overlap with existing rules.** None. C116/C117 check that a published pik_rate parses and lies in 0-20; pik_status's pik_terms proxy reads the published pik_rate. Nothing reads the PIK figure on the printed row or in the terms text, so a row with no PIK tag publishes no PIK and no rule fires.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001287750 | ARES CAPITAL CORP | rg1b | 65 | 14 | 2027.6 | pik_printed_not_published:52; pik_value_mismatch:13 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 36 | 9 | 224.8 | pik_printed_not_published:36 |
| 0001859919 | Barings Private Credit Corp | rg2 | 8 | 6 | 207.5 | pik_printed_not_published:7; pik_value_mismatch:1 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 15 | 4 | 198.5 | pik_printed_not_published:15 |
| 0001572694 | Goldman Sachs BDC, Inc. | gsxf | 7 | 2 | 132.8 | pik_member_text_only:5; pik_printed_not_published:2 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 39 | 12 | 93.3 | pik_printed_not_published:26; pik_member_text_only:11; pik_value_mismatch:2 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 5 | 5 | 92.5 | pik_printed_not_published:5 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 24 | 10 | 90.1 | pik_printed_not_published:20; pik_value_mismatch:4 |
| 0001901164 | T. Rowe Price OHA Select Private Credit Fund | trxd | 10 | 3 | 83.3 | pik_printed_not_published:10 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 6 | 2 | 58.2 | pik_printed_not_published:6 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 2 | 2 | 39.1 | pik_printed_not_published:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 6 | 4 | 7.5 | pik_value_mismatch:6 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 7 | 3 | 3.0 | pik_member_text_only:4; pik_value_mismatch:3 |
| 0001976336 | Antares Private Credit Fund | atxc | 1 | 1 | 2.8 | pik_printed_not_published:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 1 | 1 | 2.6 | pik_printed_not_published:1 |
| 0001916099 | Diameter Credit Co | dixc | 1 | 1 | 1.9 | pik_member_text_only:1 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 1 | 1 | 1.8 | pik_printed_not_published:1 |
| 0001899017 | Bain Capital Private Credit | bnxd | 1 | 1 | 1.6 | pik_printed_not_published:1 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 3 | 3 | 1.4 | pik_printed_not_published:2; pik_member_text_only:1 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 1 | 1 | 0.5 | pik_printed_not_published:1 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 1 | 1 | 0.3 | pik_printed_not_published:1 |
| 0001913724 | TPG Twin Brook Capital Income Fund | rg2 | 2 | 1 | 0.1 | pik_printed_not_published:2 |
| 0002008748 | Lord Abbett Private Credit Fund | layf | 1 | 1 | -0.1 | pik_printed_not_published:1 |

**Read of the samples below (agent; not a disposition).** Printed on the row, not published: 10 of 10 real (MidCap KLO 'SOFR+500 PIK', Ares WorkWave '10.90% PIK', Crescent 'including 50 PIK', HPS VetCor '14.75% PIK', Sixth Street Volante '16.50% PIK'). Mismatch: 10 of 10 real by the review's standard: pik_rate holds the all-in coupon (Ares '11.95% (3.50% PIK)' published 11.95, 7 rows) or the spread (Blue Owl Kaseya 6.25, Barings Marmoutier 5.75 for '5.75%, 6.7% PIK'). Member-only (weaker): mixed, as expected; Goldman Sachs BDC Gainsight 'S + 6.75 PIK' has no printed row to check, Crescent Lighthouse and iLending print no PIK on the row.

Sample of 10 flagged rows (kind pik_printed_not_published), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | MidCap Financial Investment ... 2024-03-31 | pik_printed_not_published / page | KLO Holdings, LLC 1244311 B.C. Ltd. | 1,253,000 |  | 5.0 | First Lien Secured Debt / SOFR+500 PIK, 1.00% Floor / 09/30/25 / 1,281 / 1,281 / 1,253 / (17)(30) |
| 2 | MidCap Financial Investment ... 2024-09-30 | pik_printed_not_published / page | Kauffman Intermediate, LLC | 1,165,000 |  | 5.5 | First Lien Secured Debt - Revolver / SOFR+ 550 PIK plus 1.00% Cash, 1.00% Floor / 05/08/25 / 1,235 / 1,246 / 1,165 / (9)(21)(23)(31)(32) |
| 3 | ARES CAPITAL CORP 2022-09-30 | pik_printed_not_published / page | WorkWave Intermediate II, LLC | 65,600,000 |  | 10.9 | WorkWave Intermediate II, LLC (15) / Provider of cloud-based field services and fleet management solutions / First lien senior secured loan / 10.90% PIK / SOFR (Q) / 7.25% / 6/2021 / 6/2027 / 65.6 / 65.6 / 65.6 / (2)(11) |
| 4 | ARES CAPITAL CORP 2024-12-31 | pik_printed_not_published / page | LifeStyles Bidco Ltd., Lifestyles US Holdco, Inc. ... | 3,700,000 |  | 8.0 | Preferred units / 8.00% PIK / 11/2022 / 3,178 / 3.7 / 3.7 / (2)(6) |
| 5 | Crescent Capital BDC, Inc. 2023-12-31 | pik_printed_not_published / page | Integro Parent, Inc. | 706,000 |  | 12.25 | Integro Parent, Inc. (11) / Senior Secured First Lien Term Loan / S + 1225 PIK (100 Floor) / 16.83% / 706 / 706 / 0.1 / 706 |
| 6 | Crescent Capital BDC, Inc. 2023-12-31 | pik_printed_not_published / page | Ruffalo Noel Levitz, LLC | 295,000 |  | 0.5 | Ruffalo Noel Levitz, LLC / Unitranche First Lien Revolver / S + 600 (100 Floor) (including 50 PIK) / 11.47% / 05/2024 / 303 / 303 / 0.0 / 295 |
| 7 | Crescent Capital BDC, Inc. 2024-06-30 | pik_printed_not_published / page | List Partners, Inc | 310,000 |  | 0.5 | List Partners, Inc. (5) / Senior Secured First Lien Revolver / S + 600 (100 Floor) (including 50 PIK) / 11.44% / 06/2025 / 315 / 314 / 0.0 / 310 |
| 8 | Crescent Capital BDC, Inc. 2025-03-31 | pik_printed_not_published / page | BioAgilytix | 652,000 |  | 11.21 | BioAgilytix / Senior Secured First Lien Delayed Draw Term Loan / 1121 PIK / 11.21% / 12/2028 / 791 / 783 / 0.1 / 652 |
| 9 | HPS Corporate Lending Fund 2026-03-31 | pik_printed_not_published / page | VetCor Group Holdings LLC | 304,000 |  | 14.75 | VetCor Group Holdings LLC (4)(7) / 14.75% PIK / 14.75 / % / 9/3/2030 / 333 / 329 / 304 |
| 10 | Sixth Street Lending Partner... 2023-12-31 | pik_printed_not_published / page | Volante Technologies, Inc. | 2,598,000 |  | 16.5 | Volante Technologies, Inc. / First-lien loan ($2,604 par, due 9/2028) / 9/29/2023 / 16.50 / % / 16.50% PIK / 2,578 / 2,598 / 0.1 / % |

Sample of 10 flagged rows (kind pik_value_mismatch, reported separately), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2023-06-30 | pik_value_mismatch / page | Reef Lifestyle, LLC | 14,700,000 | 10.99 | 2.0 | First lien senior secured revolving loan / 10.99% (2.00% PIK) / SOFR (Q) / 5.75% / 10/2018 / 02/2025 / 16.3 / 16.3 / 14.7 / (2)(11)(14) |
| 2 | ARES CAPITAL CORP 2024-09-30 | pik_value_mismatch / page | Premier Specialties, Inc. and RMCF V CIV XLIV, L.P... | 25,900,000 | 11.95 | 3.5 | First lien senior secured loan / 11.95% (3.50% PIK) / SOFR (M) / 7.00% / 08/2021 / 08/2027 / 27.8 / 27.8 / 25.9 / (2)(11) |
| 3 | ARES CAPITAL CORP 2024-09-30 | pik_value_mismatch / page | Production Resource Group, L.L.C. and PRG III, LLC | 48,300,000 | 17.86 | 10.1 | Production Resource Group, L.L.C. and PRG III, LLC (4) / Provider of rental equipment, labor, production management, scenery, and other products to various entertainment end-markets / First lien senior secured loan / 17.86% (10.10% PIK) / SOFR (Q) / 8.50% / 08/2018 / 08/2029 / 48.3 / 48.3 / 48.3 / (2)(11) |
| 4 | ARES CAPITAL CORP 2025-03-31 | pik_value_mismatch / page | Production Resource Group, L.L.C. and PRG III, LLC | 28,200,000 | 11.95 | 8.95 | First lien senior secured loan / 11.95% (8.95% PIK) / SOFR (Q) / 7.50% / 05/2024 / 08/2029 / 28.2 / 28.0 / 28.2 / (2)(10) |
| 5 | ARES CAPITAL CORP 2025-03-31 | pik_value_mismatch / page | Radiant Intermediate Holding, LLC | 1,800,000 | 10.41 | 3.0 | Radiant Intermediate Holding, LLC / Provider of HVAC, plumbing and electrical services / First lien senior secured loan / 10.41% (3.00% PIK) / SOFR (Q) / 6.00% / 04/2023 / 11/2026 / 2.1 / 2.1 / 1.8 / (2)(10) |
| 6 | ARES CAPITAL CORP 2025-03-31 | pik_value_mismatch / page | Convey Health Solutions, Inc. | 100,000 | 9.569999999999999 | 4.25 | Convey Health Solutions, Inc. / Healthcare workforce management software provider / First lien senior secured loan / 9.57% (4.25% PIK) / SOFR (S) / 5.25% / 02/2022 / 07/2029 / 0.1 / 0.1 / 0.1 / (2)(6)(10) |
| 7 | ARES CAPITAL CORP 2025-06-30 | pik_value_mismatch / page | Convey Health Solutions, Inc. | 1,500,000 | 9.65 | 4.25 | Convey Health Solutions, Inc. / Healthcare workforce management software provider / First lien senior secured loan / 9.65% (4.25% PIK) / SOFR (Q) / 5.25% / 09/2019 / 07/2029 / 1.9 / 1.9 / 1.5 / (2)(6)(10) |
| 8 | ARES CAPITAL CORP 2025-09-30 | pik_value_mismatch / page | The Arcticom Group, LLC and AMCP Mechanical Holdin... | 200,000 | 12.16 | 4.5 | First lien senior secured loan / 12.16% (4.50% PIK) / SOFR (M) / 8.00% / 08/2022 / 12/2027 / 0.2 / 0.2 / 0.2 / (2)(9) |
| 9 | Blue Owl Credit Income Corp. 2023-09-30 | pik_value_mismatch / page | Kaseya Inc. | 265,000 | 6.25 | 2.5 | Kaseya Inc.(7)(17)(19) / First lien senior secured delayed draw term loan / SR + / 6.25% (2.50% PIK) / 06/2024 / 265 / 227 / 265 / 0.0 / % |
| 10 | Blue Owl Credit Income Corp. 2024-06-30 | pik_value_mismatch / page | CivicPlus, LLC | 4,590,000 | 5.75 | 2.5 | CivicPlus, LLC(7) / First lien senior secured delayed draw term loan / SR + / 5.75% (2.50% PIK) / 08/2027 / 4,590 / 4,563 / 4,590 / 0.0 / % |

Sample of 10 flagged rows (weaker kind pik_member_text_only), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | Goldman Sachs BDC, Inc. 2023-06-30 | pik_member_text_only / member | Gainsight, Inc. | 46,056,000 |  | 6.75 | member: Investment 1st Lien/Senior Secured Debt - 198.48% Gainsight, Inc. Industry Software Interest Rate 11.58% Reference Rate and Spread S + 6.75 PIK Maturity 07/30/27 ; page: s S + 8.25 % 05/01/28 2,111 - - (6) (8) Gainsight, Inc. Software 11.58 % S + 6.75 % PIK 07/30/27 47,237 46,706 46,056 (6) (7) Gainsight, Inc. Software 1... |
| 2 | Goldman Sachs BDC, Inc. 2023-06-30 | pik_member_text_only / member | SPay, Inc. (dba Stack Sports) | 1,078,000 | 9.25 | 3.5 | member: Investment 1st Lien/Senior Secured Debt - 198.48% SPay, Inc. (dba Stack Sports) Industry Interactive Media & Services Interest Rate 14.49% Reference Rate and Spread S + 9.25% (incl. 3.50% PIK) Maturit... ; page: 27 1,900 ( 31 ) ( 33 ) (6) (7) (8) (11) SPay, Inc. (dba Stack Sports) Interactive Media & Services 14.45 % S +... |
| 3 | Crescent Capital BDC, Inc. 2023-12-31 | pik_member_text_only / member | Granicus, Inc. | 9,115,000 |  | 1.5 | member: Investments United States Debt Investments Software & Services Granicus, Inc. Investment Type Unitranche First Lien Term Loan Interest Term S + 700 (100 Floor) (including 150 PIK) Interest Rate 12.47%... ; page: es Debt Investments Software & Services Granicus, Inc. Investment Type Unitranche First Lien Term Loan Interes... |
| 4 | Crescent Capital BDC, Inc. 2024-12-31 | pik_member_text_only / member_page_silent | iLending LLC | 2,407,000 |  | 2.0 | iLending LLC (9) / Senior Secured First Lien Term Loan / 06/2026 / 4,385 / 4,385 / 0.3 / 2,407 |
| 5 | Crescent Capital BDC, Inc. 2024-12-31 | pik_member_text_only / member_page_silent | Mario Purchaser, LLC | 475,000 | 5.753 | 10.75 | Mario Purchaser, LLC / Unitranche First Lien Delayed Draw Term Loan / S + 575.3 (100 Floor) / 10.21% / 04/2029 / 475 / 392 / 0.1 / 475 |
| 6 | Crescent Capital BDC, Inc. 2024-12-31 | pik_member_text_only / member_page_silent | Envocore Holding, LLC | 1,514,000 |  | 10.0 | Envocore Holding, LLC (7)(8)(9) / Senior Secured Second Lien Term Loan / 12/2026 / 9,381 / 7,052 / 0.2 / 1,514 |
| 7 | Crescent Capital BDC, Inc. 2025-12-31 | pik_member_text_only / member_page_silent | Lighthouse Lab Services | 1,066,000 |  | 0.75 | Lighthouse Lab Services (5) / Senior Secured First Lien Revolver / S + 575 (100 Floor) / 9.57% / 10/2027 / 1,074 / 1,066 / 0.2 / 1,066 |
| 8 | Crescent Capital BDC, Inc. 2025-12-31 | pik_member_text_only / member_page_silent | Lighthouse Lab Services | 5,442,000 |  | 0.75 | Lighthouse Lab Services / Senior Secured First Lien Term Loan / S + 575 (100 Floor) / 9.90% / 10/2027 / 5,479 / 5,437 / 0.8 / 5,442 |
| 9 | AB Private Credit Investors ... 2025-12-31 | pik_member_text_only / member | American Physician Partners, LLC | 0 | 3.5000000000000004 | 3.0 | member: US Corporate Debt / 1st Lien/Senior Secured Debt / American Physician Partners, LLC / Healthcare / Delayed Draw Term Loan / —% (S + 6.75%; 1.00% Floor; 3.00% PIK) / 3/31/2026 ; page: 2030 1,321,971 1,310,950 1,302,141 (15) American Physician Partners, LLC Healthcare Term Loan - ( S + 6.75 %; 1.00 % Floor; 3.00 % PIK) 3/3... |
| 10 | Antares Strategic Credit Fun... 2025-06-30 | pik_member_text_only / member_page_silent | Accelerate Topco Holdings LLC | 418,000 |  | 10.5 | Accelerate Topco Holdings LLC / (11)(15) / Common / — / — / — / 6 / 222 / 418 / 0.02 |

## industry_not_published

**Overlap with existing rules.** Partial. field_coverage_drop ('filer industry', extracted_industry) fires on a fall of 20 points against the fund's previous quarter with 20+ funded rows; it is blind to a fund's first quarters (Golub 2023, Stone Point 2023-24) and to a gap that never closes (Guardian IV). It also reads extracted_industry, while the public sector partition reads gics_sub_industry (pipeline/public_partitions.py). This candidate reads gics_sub_industry and reports both.

Levels (D-207: finding below 0.80, warning below 0.90): finding 59, warning 61, ok 491, too_few_rows 11, exempt 5.

Exempt: 0002049733 Blackstone Private Real Estate Credit and Income Fund (checked 2026-10-18). Evidence: Schedule headings are asset types (CMBS, RMBS, mezzanine loans) and loans are named by property ('1100 Peachtree', '18200-18250 Flower Hill Way'); the printed rows carry no industry cell and extracted_industry is empty on every row of 2025-06-30 to 2026-06-30 (sandbox brxb). Read in the cached filings by the 2026-10-18 false-alarm review (docs/investigations/v05_rule_candidates_falsealarm_2026-10-18.md, rule 4: 5 of 5 sampled fund-quarters print none).

Warning fund-quarters (no rows raised): New Mountain Guardian IV BDC, ... 2024-09-30 0.800; HPS Corporate Lending Fund 2024-06-30 0.803; HPS Corporate Lending Fund 2024-09-30 0.803; HPS Corporate Lending Fund 2023-06-30 0.803; Apollo Debt Solutions BDC 2026-03-31 0.805; NMF SLF I, Inc. 2023-09-30 0.806; NMF SLF I, Inc. 2025-03-31 0.808; NMF SLF I, Inc. 2023-06-30 0.809; NMF SLF I, Inc. 2023-03-31 0.809; New Mountain Guardian IV BDC, ... 2024-06-30 0.810; Trinity Capital Inc. 2026-03-31 0.813; NMF SLF I, Inc. 2023-12-31 0.814; NMF SLF I, Inc. 2024-12-31 0.815; Carlyle Credit Solutions, Inc. 2026-03-31 0.817; New Mountain Guardian IV BDC, ... 2024-12-31 0.820; HPS Corporate Lending Fund 2023-12-31 0.823; HPS Corporate Lending Fund 2023-09-30 0.823; Sixth Street Specialty Lending... 2023-03-31 0.824; New Mountain Guardian IV BDC, ... 2025-03-31 0.825; Sixth Street Specialty Lending... 2023-06-30 0.827; HPS Corporate Lending Fund 2024-03-31 0.835; New Mountain Guardian IV BDC, ... 2023-03-31 0.837; Sixth Street Specialty Lending... 2023-09-30 0.840; Sixth Street Specialty Lending... 2023-12-31 0.841; Carlyle Credit Solutions, Inc. 2025-03-31 0.846; Carlyle Credit Solutions, Inc. 2025-06-30 0.848; Apollo Debt Solutions BDC 2025-12-31 0.855; Carlyle Credit Solutions, Inc. 2025-09-30 0.861; Barings Private Credit Corp 2023-06-30 0.861; AB Private Credit Investors Co... 2024-06-30 0.864; Trinity Capital Inc. 2023-03-31 0.867; Barings Private Credit Corp 2024-09-30 0.868; AB Private Credit Investors Co... 2025-12-31 0.868; Carlyle Credit Solutions, Inc. 2025-12-31 0.868; AB Private Credit Investors Co... 2023-12-31 0.869; Barings Private Credit Corp 2023-03-31 0.870; AB Private Credit Investors Co... 2024-03-31 0.870; AB Private Credit Investors Co... 2023-09-30 0.872; AB Private Credit Investors Co... 2026-03-31 0.872; Barings Private Credit Corp 2023-09-30 0.873; Apollo Debt Solutions BDC 2025-09-30 0.877; AB Private Credit Investors Co... 2024-09-30 0.878; Barings Private Credit Corp 2024-03-31 0.879; AB Private Credit Investors Co... 2024-12-31 0.880; Barings Private Credit Corp 2023-12-31 0.880; Trinity Capital Inc. 2023-06-30 0.881; AB Private Credit Investors Co... 2025-03-31 0.881; Barings Private Credit Corp 2024-06-30 0.883; Sixth Street Specialty Lending... 2026-03-31 0.884; Apollo Debt Solutions BDC 2025-06-30 0.887; Sixth Street Specialty Lending... 2025-09-30 0.888; Apollo Debt Solutions BDC 2025-03-31 0.888; Trinity Capital Inc. 2025-12-31 0.888; Sixth Street Specialty Lending... 2025-12-31 0.889; Apollo Debt Solutions BDC 2024-06-30 0.889; Apollo Debt Solutions BDC 2024-09-30 0.890; Sixth Street Specialty Lending... 2026-06-30 0.890; AB Private Credit Investors Co... 2025-09-30 0.890; AB Private Credit Investors Co... 2025-06-30 0.891; Apollo Debt Solutions BDC 2023-12-31 0.891; Apollo Debt Solutions BDC 2024-12-31 0.895.

Coverage distribution, fund-quarters with 20+ funded rows (n = 616 of 627):

| coverage below | gics_sub_industry (published) | extracted_industry (filer) |
|---|---:|---:|
| 0.50 | 16 | 92 |
| 0.80 | 64 | 94 |
| 0.90 | 125 | 116 |
| 0.95 | 159 | 141 |
| 0.98 | 203 | 157 |
| 0.99 | 240 | 168 |
| 1.00 | 291 | 228 |

gics_sub_industry coverage percentiles: p05 0.671, p10 0.793, p25 0.941, median 1.000. Threshold used for the flagged rows below: 0.80 (owner ruling D-207). The distribution includes exempt funds.

Lowest 15 fund-quarters:

| cik | fund | quarter | funded rows | gics coverage | extracted coverage | FV without gics (M) |
|---|---|---|---:|---:|---:|---:|
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-06-30 | 65 | 0.015 | 0.000 | 481.9 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-09-30 | 94 | 0.032 | 0.000 | 672.0 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2026-06-30 | 121 | 0.041 | 0.000 | 1418.3 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2026-03-31 | 107 | 0.047 | 0.000 | 1355.3 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-12-31 | 113 | 0.053 | 0.000 | 912.9 |
| 0002012139 | Fortress Private Lending Fund | 2025-06-30 | 39 | 0.205 | 0.051 | 288.0 |
| 0002008748 | Lord Abbett Private Credit Fund | 2025-03-31 | 37 | 0.216 | 0.000 | 376.3 |
| 0002008748 | Lord Abbett Private Credit Fund | 2024-09-30 | 20 | 0.250 | 0.000 | 138.8 |
| 0002008748 | Lord Abbett Private Credit Fund | 2025-09-30 | 51 | 0.255 | 0.000 | 605.3 |
| 0002008748 | Lord Abbett Private Credit Fund | 2024-12-31 | 31 | 0.258 | 0.000 | 255.2 |
| 0002008748 | Lord Abbett Private Credit Fund | 2025-12-31 | 81 | 0.259 | 0.000 | 916.4 |
| 0002008748 | Lord Abbett Private Credit Fund | 2025-06-30 | 46 | 0.261 | 0.000 | 540.4 |
| 0001742313 | Monroe Capital Income Plus Corp | 2023-09-30 | 382 | 0.314 | 0.003 | 1372.2 |
| 0001742313 | Monroe Capital Income Plus Corp | 2023-06-30 | 364 | 0.319 | 0.003 | 1207.1 |
| 0002008748 | Lord Abbett Private Credit Fund | 2026-03-31 | 97 | 0.320 | 0.000 | 981.1 |

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001838126 | HPS Corporate Lending Fund | rg1b | 634 | 5 | 8983.6 | no_industry_at_all:634 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 156 | 1 | 6915.1 | no_industry_at_all:156 |
| 0002008748 | Lord Abbett Private Credit Fund | layf | 265 | 7 | 3813.6 | no_industry_at_all:265 |
| 0001742313 | Monroe Capital Income Plus Corp | rg2 | 740 | 3 | 3625.8 | no_industry_at_all:737; filer_industry_not_mapped:3 |
| 0001825384 | Stone Point Credit Corp | stxf | 387 | 8 | 3312.9 | no_industry_at_all:387 |
| 0002037804 | New Mountain Private Credit Fund | npxd | 481 | 7 | 3272.2 | no_industry_at_all:481 |
| 0001925531 | New Mountain Guardian IV BDC, L.L.C. | ngxd | 500 | 9 | 3085.5 | no_industry_at_all:500 |
| 0001766037 | NMF SLF I, Inc. | nmyd | 544 | 8 | 2152.3 | no_industry_at_all:544 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 272 | 6 | 1823.2 | no_industry_at_all:272 |
| 0001786108 | Trinity Capital Inc. | tcxe | 113 | 1 | 831.2 | filer_industry_not_mapped:67; no_industry_at_all:46 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 280 | 2 | 793.9 | no_industry_at_all:280 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 58 | 1 | 367.6 | filer_industry_not_mapped:29; no_industry_at_all:29 |
| 0002012139 | Fortress Private Lending Fund | foxd | 31 | 1 | 288.0 | no_industry_at_all:31 |

**Read of the samples below (agent; not a disposition).** 10 of 10 are funded rows with no published industry. Carlyle prints 'Construction & Building' on the row; New Mountain prints the industry cell under each company; HPS prints industry as section headings (the review's correction). Fillable gaps, not coverage limits. Blackstone Private Real Estate Credit is now exempt with evidence.

Sample of 10 flagged rows, seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | Carlyle Credit Solutions, In... 2026-06-30 | no_industry_at_all / coverage | Chartwell Cumming Holding Corporation | 2,664,000 |  |  | Chartwell Cumming Holding Corporation / (c) / (2)(3)(15) / Construction & Building / SOFR / 4.75% / 8.48% / 6/16/2026 / 6/16/2033 / 2,780 / 2,664 / 2,664 / 0.15 |
| 2 | NMF SLF I, Inc. 2025-09-30 | no_industry_at_all / coverage | FS WhiteWater Borrower, LLC | 2,472,000 |  |  | First Lien(3) / SOFR(Q) / 5.00% / 9.15% / 12/2021 / 12/2029 / 2,472 / 2,459 / 2,472 |
| 3 | NMF SLF I, Inc. 2025-12-31 | no_industry_at_all / coverage | LogRhythm, Inc. | 2,596,000 |  |  | Software / First Lien(2)(3)(6) / SOFR(Q) / 7.50% / 11.34% / 07/2024 / 07/2029 / 2,727 / 2,697 / 2,596 / 0.26 / % |
| 4 | HPS Corporate Lending Fund 2024-12-31 | no_industry_at_all / coverage | Elements Finco Limited | 10,535,000 |  |  | Elements Finco Limited (4)(5)(7) / SF + / 4.75% / 9.11 / % / 4/29/2031 / 10,431 / 10,337 / 10,535 |
| 5 | HPS Corporate Lending Fund 2024-12-31 | no_industry_at_all / coverage | Columbia Cent CLO 33 Ltd | 2,031,000 |  |  | Columbia Cent CLO 33 Ltd (5)(7) / SF + / 7.16% / 11.78 / % / 4/20/2037 / 2,000 / 1,962 / 2,031 |
| 6 | HPS Corporate Lending Fund 2025-03-31 | no_industry_at_all / coverage | Madonna Bidco Limited | 276,000 |  |  | Madonna Bidco Limited (4)(5)(6)(7) / SN + / 5.25% / 9.71 / % / 10/25/2031 / £ / 10,435 / 143 / 276 |
| 7 | HPS Corporate Lending Fund 2025-03-31 | no_industry_at_all / coverage | TriMech Acquisition Corp. | 46,241,000 |  |  | TriMech Acquisition Corp. (4)(10) / SN + / 4.75% / 9.12 / % / 3/10/2028 / £ / 35,793 / 43,472 / 46,241 |
| 8 | HPS Corporate Lending Fund 2025-09-30 | no_industry_at_all / coverage | Marcone Group Inc | 10,140,000 |  |  | Marcone Group Inc (4)(9) / SF + / 7.00% (incl 3.25% PIK) / 11.44 / % / 6/23/2028 / 12,153 / 12,098 / 10,140 |
| 9 | New Mountain Guardian IV BDC... 2025-09-30 | no_industry_at_all / coverage | KENE Acquisition, Inc. | 3,483,000 |  |  | Business Services / First Lien(4)(7)(8) / SOFR(Q) / + / 5.25% / 9.56% / 02/2024 / 02/2031 / 3,483 / 3,454 / 3,483 |
| 10 | HPS Corporate Capital Soluti... 2024-06-30 | no_industry_at_all / coverage | Bakelite US Holdco Inc | 2,011,000 |  |  | Bakelite US Holdco Inc (8)(14) / SF+ / 3.50% / 8.83 / % / 5/29/2029 / 2,000 / 2,013 / 2,011 |

## preferred_published_as_common

**Overlap with existing rules.** Partial. Column rule X01 flags a PRIVATE_EQUITY row not classed PREFERRED_EQUITY with interest_rate > 0, so it catches a dividend rate on a common row but not a PIK-only rate (Commonwealth LNG, KWOR publish pik_rate and no interest_rate) and never the text. Oracle C05 is a global share of rows whose instrument text says common and carry a rate. No rule reads 'preferred' on the printed row against the class. Text kinds only since D-207 (the first run's rate_on_common, 399 rows, is gone).

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 9 | 2 | 766.6 | text_and_rate:9 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 7 | 7 | 374.2 | text_says_preferred:7 |
| 0001287750 | ARES CAPITAL CORP | rg1b | 3 | 3 | 79.7 | text_and_rate:3 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 3 | 2 | 78.2 | text_says_preferred:3 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 9 | 7 | 49.6 | text_says_preferred:9 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 101 | 14 | 46.2 | preferred_heading_only:100; text_says_preferred:1 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 12 | 5 | 24.0 | text_and_rate:9; text_says_preferred:3 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 3 | 3 | 10.8 | text_and_rate:2; text_says_preferred:1 |

**Read of the samples below (agent; not a disposition).** 9 of 10 real: the filer says preferred or preference and the build publishes common (Ares McLaren 'Senior preference shares', Blue Owl PCF 'Series A Preferred Units', North Haven Vardiman 'Preferred Equity', AB venture rows under 'U.S. Preferred Stock'). 1 unclear: AB Avant 'Class A Units' listed under the filer's 'U.S. Preferred Stock' heading (the review's Swyft shape). AB is 101 of the 147 rows. (Read on the 2026-10-18 run. Since 2026-10-19 heading-only rows, 100, all AB, are the weaker kind preferred_heading_only, so the AB venture rows and Avant leave the findings; 47 remain.)

Sample of 10 flagged rows (finding kinds), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2022-09-30 | text_and_rate / page | McLaren Group Limited | 25,000,000 | EQUITY_COMMON/COMMON_EQUITY pik=12.5 rate= | Senior preference shares | McLaren Group Limited / Automobile manufacturer and retailer / Senior preference shares / 12.50% PIK / 8/2021 / 8/2028 / 200,000 / 23.7 / 25.0 / (2)(6) |
| 2 | Sixth Street Specialty Lendi... 2025-06-30 | text_says_preferred / page | Lucidworks, Inc. | 650,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Class A Units (2,333,333 Units) Initial Acquisition Date 4/1... | Lucidworks, Inc. (11) / Series F Preferred Shares (199,054 shares) / 8/2/2019 / 800 / 650 / 0.0 / % |
| 3 | Sixth Street Specialty Lendi... 2025-12-31 | text_says_preferred / page | Elysium BidCo Limited | 7,581,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Convertible Preference Shares (4,976,563 Shares) Initial Acq... | Elysium BidCo Limited (4)(11) / Convertible Preference Shares (4,976,563 Shares) / 12/11/2024 / 6,341 / 7,581 (GBP 5,636) / 0.5 / % |
| 4 | Blue Owl Credit Income Corp. 2023-03-31 | text_and_rate / page | PCF Holdco, LLC (dba PCF Insurance Services) | 5,254,000 | EQUITY_COMMON/COMMON_EQUITY pik=15.0 rate= |  | PCF Holdco, LLC (dba PCF Insurance Services)(16)(17)(19)(24) / Series A Preferred Units / 15.00% PIK / N/A / 5,254 / 5,252 / 5,254 / 0.1 / % |
| 5 | North Haven Private Income F... 2024-09-30 | text_and_rate / page | Vardiman Black Holdings, LLC | 3,109,000 | EQUITY_COMMON/COMMON_EQUITY pik=6.0 rate= |  | Vardiman Black Holdings, LLC / (6) (16) / Preferred Equity / 6.00% PIK / 3/29/2024 / 7,065,190 / 4,689 / 3,109 / 0.10 |
| 6 | North Haven Private Income F... 2024-09-30 | text_and_rate / page | Eclipse Topco, Inc. | 3,035,000 | EQUITY_COMMON/COMMON_EQUITY pik=12.5 rate= |  | Eclipse Topco, Inc. / (6) (16) / Preferred Equity / 12.50% PIK / 9/5/2024 / 310 / 3,035 / 3,035 / 0.10 |
| 7 | North Haven Private Income F... 2024-12-31 | text_and_rate / page | Eclipse Topco, Inc. | 3,036,000 | EQUITY_COMMON/COMMON_EQUITY pik=12.5 rate= |  | Eclipse Topco, Inc. / (6) (16) / Preferred Equity / 12.50% PIK / 09/05/2024 / 310 / 3,048 / 3,036 / 0.09 |
| 8 | North Haven Private Income F... 2025-03-31 | text_and_rate / page | Eclipse Topco, Inc. | 3,083,000 | EQUITY_COMMON/COMMON_EQUITY pik=12.5 rate= |  | Eclipse Topco, Inc. / (6) (18) / Preferred Equity / 12.50% PIK / 9/5/2024 / 310 / 3,048 / 3,083 / 0.09 |
| 9 | Sixth Street Lending Partner... 2025-03-31 | text_says_preferred / page | Elysium BidCo Limited | 49,697,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Convertible Preference Shares (38,503,125 units) Initial Acq... | Elysium BidCo Limited (4)(8)(10) / Convertible Preference Shares (38,503,125 units) / 12/11/2024 / 49,063 / 49,697 (GBP 38,502) / 1.2 / % |
| 10 | Sixth Street Lending Partner... 2026-06-30 | text_says_preferred / page | Elysium BidCo Limited | 53,403,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Convertible Preference Shares (38,503,125 Shares) Initial Ac... | Elysium BidCo Limited (4)(9) / Convertible Preference Shares (38,503,125 units) / 12/11/2024 / 49,063 / 53,403 (GBP 40,236) / 1.2 / % |

Sample of 10 flagged rows (weaker kind preferred_heading_only), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | AB Private Credit Investors ... 2023-03-31 | preferred_heading_only / member | Heap Inc. | 148,758 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series D | member: Heap Inc.One - U.s.preferred Stock At Two Point Zero Three Percentage - Series D ; (issuer's first words not found on the visible page) |
| 2 | AB Private Credit Investors ... 2023-03-31 | preferred_heading_only / member | Heap Inc. | 1,033,815 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series C | member: Heap Inc. - U.s.preferred Stock At Two Point Zero Three Percentage - Series C ; (issuer's first words not found on the visible page) |
| 3 | AB Private Credit Investors ... 2023-03-31 | preferred_heading_only / member | Vectra AI Inc | 110,279 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series F | member: Vectra AI Inc - U.s.preferred Stock At Two Point Zero Three Percentage - Series F ; (issuer's first words not found on the visible page) |
| 4 | AB Private Credit Investors ... 2023-06-30 | preferred_heading_only / member | Phenom People Inc. | 431,871 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series C | member: Phenom People Inc. - U.s.Preferred Stock At Two Point Zero Two Percentage - Series C ; (issuer's first words not found on the visible page) |
| 5 | AB Private Credit Investors ... 2023-09-30 | preferred_heading_only / member | Heap Inc | 848,035 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series C | Heap, Inc.(11) / Series C / Software & Tech Services / 05/21/2019 / 189,617 / 696,352 / 848,035 |
| 6 | AB Private Credit Investors ... 2023-09-30 | preferred_heading_only / member | Symplr Software Intermediate Holdings Inc. | 2,077,310 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series A | Symplr Software Intermediate Holdings, Inc.(11) / Series A / Software & Tech Services / 11/30/2018 / 1,196 / 1,160,532 / 2,077,310 |
| 7 | AB Private Credit Investors ... 2023-12-31 | preferred_heading_only / member | Phenom People, Inc. | 395,180 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series C | Phenom People, Inc. (11) / Series C / Software & Tech Services / 01/08/2020 / 35,055 / 220,610 / 395,180 |
| 8 | AB Private Credit Investors ... 2024-03-31 | preferred_heading_only / member | Concerto HealthAI Solutions LLC | 329,633 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series B-1 | Concerto HealthAI Solutions LLC(11) (12) / Series B-1 / Software & Tech Services / 12/23/2019 / 65,614 / 349,977 / 329,633 |
| 9 | AB Private Credit Investors ... 2024-09-30 | preferred_heading_only / member | Concerto HealthAI Solutions LLC | 304,455 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series B-1 | Concerto HealthAI Solutions LLC / Series B-1 / Software & Tech Services / 12/23/2019 / 65,614 / 349,977 / 304,455 |
| 10 | AB Private Credit Investors ... 2026-06-30 | preferred_heading_only / member | Datarobot, Inc. | 66,794 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series E | Datarobot, Inc. / Series E / Software / 8/31/2019 / 38,190 / 289,278 / 66,794 |

## Ledger wiring (2026-10-19)

The five rules now produce findings through the shadow identity engine (`scripts/shadow_identity_engine.py`, `ensure_page_rules`), ledger names: `issuer_name_printed` (issuer_name_differs_from_page), `units_printed` (unit_count_differs_from_row_text), `pik_printed` (pik_printed_not_published), `industry_coverage` (industry_not_published), `preferred_printed` (preferred_published_as_common). Only these finding kinds raise: issuer_name_printed: begins_with_industry_label, begins_with_section_word, equals_industry_label, holds_category_path, not_the_printed_name, spacing_only; units_printed: labelled_count_differs, labelled_count_not_published, proxy_count_not_on_row; pik_printed: pik_printed_not_published, pik_value_mismatch; industry_coverage: filer_industry_not_mapped, no_industry_at_all; preferred_printed: text_and_rate, text_says_preferred. Weaker kinds and rule 1's blind-spot table go to `data/output/shadow/page_rules_informational.csv` and `page_rules_name_blind_spots.csv`; a fund-quarter with no tested row gets no ledger result.

## Changelog entries (to append to docs/agent_changelog.md on merge)

### 2026-10-17 - Five candidate page rules built and measured, not switched on
- New `pipeline/candidate_rules.py` (issuer name, unit count, PIK, industry coverage, preferred-as-common): DuckDB over published rows joined to the page reader's `printed_row`. Measured on the 51 accepted sandboxes (`docs/investigations/v05_rule_candidates_2026-10-17.md`). 18 tests.

### 2026-10-18 - Candidate page rules revised after the false-alarm review (D-207)
- Rule 1 legal-form tails, blind-quarter suppression and blind-spot table; rule 2 issuer name stripped, printed count passes, `units_scale_unclear`; rule 3 page-only findings, `pik_member_text_only`; rule 4 finding < 0.80, warning < 0.90, Blackstone Private Real Estate Credit exempt with evidence; rule 5 text kinds only. Re-measured on 52 sandboxes; 26 tests.

### 2026-10-19 - Page rules wired into the ledger (D-207, orchestrator under the owner's standing delegation)
- Rule 1 passes a near spelling the fund prints for the same issuer (26North Ascend, Antares Clear Capital) and flags another group entity on the row again (MidCap Wildcat); rule 5 heading-only evidence is the weaker kind `preferred_heading_only`.
- `scripts/shadow_identity_engine.py`: `ensure_page_rules` runs the rules fund by fund over the wrapped cohort into table `page_rule_rows` (one row per tested row); five identity rules `issuer_name_printed`, `units_printed`, `pik_printed`, `industry_coverage`, `preferred_printed` (tier tight) read it, so failures reach the shadow ledger, the review queue (blocker lane) and the findings ledger like spread_printed. A fund-quarter with no tested row gets no result. `scripts/shadow_validation_runner.py` calls it before the identity rules.
- Informational, never in the ledger: `data/output/shadow/page_rules_informational.csv` (weaker kinds, rule-1 flags in untested fund-quarters), `page_rules_name_blind_spots.csv`; finding detail in `page_rule_findings.csv`.
- Tests: test_candidate_rules.py, test_shadow_identity_rules.py (+3 engine tests), test_oracle_checks.py, shadow runner / review-queue tests. No production run; dry run on the v0.5 sandbox: 74 fund-quarters tested per rule, 4,317 / 305 / 114 / 790 / 15 finding rows.

