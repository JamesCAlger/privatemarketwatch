# v0.5 candidate rules, measured on the accepted sandboxes (2026-10-17)

Owner, 2026-10-17: "do it" -- build the five candidate rules and measure them; do NOT switch them on. Code: `pipeline/candidate_rules.py` (not imported by the build, ledger, shadow engines, quarter pass or gate). Script: `scripts/v05_evidence/measure_candidate_rules.py`. Inputs: each fund's accepted sandbox in `docs/investigations/v05_readings/accepted_sandboxes.json`, published basis (no `underlying_schedule` rows). Page access: `printed_row` from that sandbox's `bdc_ixbrl_field_status` (current period, member printed once).

Files: `v05_rule_candidates_2026-10-17.csv` (rule x fund), `v05_rule_candidates_2026-10-17_rows.csv` (every flagged row), `v05_rule_candidates_2026-10-17_industry_coverage.csv` (rule 4).

Funds measured: 51; published rows: 256588; rows whose printed row is known: 246286 (96.0 pct). Funds where the page reader is (almost) never joined fall back to member text and shape tests: none.

A clean result is not 'data correct': these rules see only what the page reader joined and the shapes coded.

## Totals

| rule | rows | fund-quarters | funds | FV flagged (M) | rows on page basis | kinds |
|---|---:|---:|---:|---:|---:|---|
| issuer_name_differs_from_page | 6537 | 370 | 48 | 217529.3 | 6492 | not_the_printed_name:6299; spacing_only:193; begins_with_section_word:23; begins_with_industry_label:8; equals_industry_label:8; holds_category_path:6 |
| unit_count_differs_from_row_text | 459 | 140 | 27 | 5981.8 | 450 | proxy_count_not_on_row:418; labelled_count_differs:28; labelled_count_not_published:13 |
| pik_printed_not_published | 245 | 88 | 22 | 3271.5 | 223 | pik_printed_not_published:205; pik_value_mismatch:37; pik_value_rounding:3 |
| industry_not_published | 4676 | 57 | 13 | 40291.7 | 0 | no_industry_at_all:4577; filer_industry_not_mapped:99 |
| preferred_published_as_common | 546 | 122 | 18 | 5861.4 | 43 | rate_on_common:399; text_says_preferred:124; text_and_rate:23 |

## issuer_name_differs_from_page

**Overlap with existing rules.** Partial. Oracle I09 flags a fund-quarter where more than 5 pct of issuer names equal a GICS sub-industry label (aggregate; misses isolated rows, the filer's own labels and any name that is merely wrong). The fund gate's check_names (scripts/v05_evidence/fund_gate.py, not a ledger rule) looks for instrument words, row numbers, holder labels and a leading industry, above 1 pct of a fund's rows. Neither compares the name with the printed row, so the observed member-spelling cases (Covetrus as 'CVET Midco 2', NextCar, 'Global Solutions' for Continuum Global Solutions) pass both.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 4179 | 14 | 183220.1 | not_the_printed_name:4176; spacing_only:2; begins_with_section_word:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 122 | 14 | 8756.2 | not_the_printed_name:113; spacing_only:7; begins_with_section_word:2 |
| 0001287750 | ARES CAPITAL CORP | rg1b | 105 | 14 | 4166.1 | not_the_printed_name:87; spacing_only:12; holds_category_path:6 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 211 | 10 | 2913.3 | not_the_printed_name:211 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 34 | 6 | 2248.3 | not_the_printed_name:31; spacing_only:3 |
| 0001920145 | Goldman Sachs Private Credit Corp. | rg1b | 158 | 12 | 2169.6 | not_the_printed_name:155; spacing_only:2; begins_with_section_word:1 |
| 0001872371 | Oaktree Strategic Credit Fund | rg1b | 88 | 8 | 1089.4 | not_the_printed_name:67; begins_with_section_word:11; spacing_only:10 |
| 0001825384 | Stone Point Credit Corp | stxf | 74 | 14 | 972.6 | not_the_printed_name:66; spacing_only:8 |
| 0001766037 | NMF SLF I, Inc. | nmyd | 150 | 14 | 916.5 | not_the_printed_name:150 |
| 0002037804 | New Mountain Private Credit Fund | npxd | 77 | 7 | 905.1 | not_the_printed_name:76; equals_industry_label:1 |
| 0001965934 | Overland Advantage | ovye | 7 | 6 | 886.0 | equals_industry_label:4; not_the_printed_name:3 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 67 | 14 | 773.5 | not_the_printed_name:59; spacing_only:8 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 39 | 12 | 758.0 | not_the_printed_name:39 |
| 0001572694 | Goldman Sachs BDC, Inc. | gsxf | 91 | 12 | 752.1 | not_the_printed_name:80; begins_with_section_word:7; spacing_only:4 |
| 0001950976 | 26North BDC, Inc. | tnxc | 46 | 9 | 608.8 | not_the_printed_name:42; spacing_only:4 |
| 0001742313 | Monroe Capital Income Plus Corp | rg2 | 137 | 9 | 537.3 | not_the_printed_name:79; spacing_only:58 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 146 | 9 | 524.0 | not_the_printed_name:121; spacing_only:20; begins_with_industry_label:3; equals_industry_label:1; begins_with_section_word:1 |
| 0002031750 | Ares Core Infrastructure Fund | acxb | 3 | 3 | 456.5 | not_the_printed_name:3 |
| 0001925531 | New Mountain Guardian IV BDC, L.L.C. | ngxd | 98 | 14 | 414.8 | not_the_printed_name:98 |
| 0001772704 | Goldman Sachs Private Middle Market Credit II... | gpyf | 60 | 6 | 385.7 | not_the_printed_name:60 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 80 | 14 | 385.6 | not_the_printed_name:65; spacing_only:15 |
| 0001849894 | MSD Investment Corp. | rg2 | 6 | 3 | 383.4 | not_the_printed_name:5; spacing_only:1 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 9 | 4 | 382.1 | not_the_printed_name:9 |
| 0001899017 | Bain Capital Private Credit | bnxd | 49 | 11 | 360.3 | not_the_printed_name:45; spacing_only:4 |
| 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. | viya | 8 | 5 | 294.1 | not_the_printed_name:8 |
| 0001976336 | Antares Private Credit Fund | atxc | 58 | 7 | 224.7 | not_the_printed_name:53; begins_with_industry_label:4; equals_industry_label:1 |
| 0001920453 | Fidelity Private Credit Fund | fpxg | 42 | 11 | 210.6 | not_the_printed_name:40; spacing_only:2 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 38 | 9 | 199.4 | not_the_printed_name:38 |
| 0001859919 | Barings Private Credit Corp | rg2 | 59 | 8 | 178.7 | not_the_printed_name:54; spacing_only:4; begins_with_industry_label:1 |
| 0001916099 | Diameter Credit Co | dixc | 13 | 8 | 175.1 | not_the_printed_name:12; spacing_only:1 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 23 | 4 | 173.8 | not_the_printed_name:23 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 39 | 7 | 165.4 | not_the_printed_name:37; spacing_only:2 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 57 | 7 | 152.7 | not_the_printed_name:38; spacing_only:19 |
| 0001902649 | BlackRock Private Credit Fund | bpxh | 62 | 14 | 122.0 | not_the_printed_name:56; spacing_only:6 |
| 0001869453 | Blue Owl Technology Income Corp. | rg2 | 10 | 4 | 105.5 | not_the_printed_name:9; spacing_only:1 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 6 | 4 | 99.4 | not_the_printed_name:6 |
| 0001901164 | T. Rowe Price OHA Select Private Credit Fund | trxd | 11 | 5 | 94.2 | not_the_printed_name:11 |
| 0001950803 | Stepstone Private Credit Fund LLC | spxf | 4 | 4 | 89.2 | not_the_printed_name:3; equals_industry_label:1 |
| 0001959604 | Jefferies Credit Partners BDC Inc. | jcxd | 17 | 6 | 65.3 | not_the_printed_name:17 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 6 | 4 | 43.3 | not_the_printed_name:6 |
| 0001899996 | Fidelity Private Credit Co LLC | fcxe | 2 | 1 | 40.9 | not_the_printed_name:2 |
| 0001913724 | TPG Twin Brook Capital Income Fund | rg2 | 7 | 4 | 36.3 | not_the_printed_name:7 |
| 0002012139 | Fortress Private Lending Fund | foxd | 4 | 2 | 27.4 | not_the_printed_name:4 |
| 0001885968 | T Series BDC LLC | tsxd | 13 | 4 | 20.8 | not_the_printed_name:13 |
| 0001911066 | Nuveen Churchill Private Capital Income Fund | ncxf | 1 | 1 | 16.4 | not_the_printed_name:1 |
| 0001786108 | Trinity Capital Inc. | tcxe | 7 | 5 | 15.6 | not_the_printed_name:7 |
| 0001901612 | Golub Capital BDC 4, Inc. | g4xc | 6 | 4 | 8.9 | not_the_printed_name:6 |
| 0001975736 | KKR FS Income Trust Select | ksxf | 8 | 3 | 4.6 | not_the_printed_name:8 |

**Read of the samples below (agent, 2026-10-17; not a disposition).** 9 of 10 look like real name errors: 7 carry the member's group name in front of the legal name (Apollo Debt Solutions 'Gannett Gannett Holdings, LLC', 'CINC Systems 1475 Holdings, LLC', 'HKA Mount Olympus Bidco Limited'), one a sequence word (',Two Recochem, Inc'), one an industry prefix (BlackRock 'Technology PointClickCare'). 1 false alarm: New Mountain prints an industry heading in the row's first cell ('Consumer Products') that the heading test missed. Apollo alone is 4,179 of the flagged rows: the group-name prefix is on most of its published names. spacing_only (193) is a separate kind for 'Circus Trix'/'CircusTrix'-type differences; some of those are the page's typo, not the build's.

Sample of 10 flagged rows, seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | Goldman Sachs BDC, Inc. 2024-12-31 | not_the_printed_name / page | ,Two Recochem, Inc | 1,749,000 | ,Two Recochem, Inc | Recochem, Inc | Recochem, Inc / Chemicals / 10.32% / S + 5.75% / 11/01/30 / 1,749 / 1,718 / 1,749 / (6) (7) (8) |
| 2 | Apollo Debt Solutions BDC 2023-03-31 | not_the_printed_name / page | HKA Mount Olympus Bidco Limited | 17,173,000 | HKA Mount Olympus Bidco Limited | Mount Olympus Bidco Limited | Mount Olympus Bidco Limited / First Lien Secured Debt / S+575, 0.50% Floor / 8/9/2029 / 18,465 / 17,247 / 17,173 / (4)(8)(9)(18)(26) |
| 3 | Apollo Debt Solutions BDC 2023-12-31 | not_the_printed_name / page | Infoblox Delta Topco, Inc. | 13,332,000 | Infoblox Delta Topco, Inc. | Delta Topco, Inc. | Delta Topco, Inc. / First Lien Secured Debt / S+375, 0.75% Floor / 12/1/2027 / 13,322 / 13,326 / 13,332 / (16) |
| 4 | Apollo Debt Solutions BDC 2024-09-30 | not_the_printed_name / page | Gannett Gannett Holdings, LLC | 44,214,000 | Gannett Gannett Holdings, LLC | Gannett Holdings, LLC | Gannett Holdings, LLC / First Lien Secured Debt - Term Loan / S+511, 0.50% Floor / 10/15/2026 / 44,195 / 44,085 / 44,214 / (8)(14) |
| 5 | Apollo Debt Solutions BDC 2025-09-30 | not_the_printed_name / page | Hub International Hub International Limited | 21,246,000 | Hub International Hub International Limited | Hub International Limited | Hub International Limited / First Lien Secured Debt - Term Loan / S+225, 0.00% Floor / 6/20/2030 / 21,192 / 21,217 / 21,246 / (16) |
| 6 | Apollo Debt Solutions BDC 2025-12-31 | not_the_printed_name / page | G&A G&A Partners Holding Company II, LLC | 26,229,000 | G&A G&A Partners Holding Company II, LLC | G&A Partners Holding Company II, LLC | G&A Partners Holding Company II, LLC / First Lien Secured Debt - Term Loan / S+500, 0.75% Floor / 3/3/2031 / 26,295 / 25,983 / 26,229 / (4)(9)(16) |
| 7 | Apollo Debt Solutions BDC 2026-03-31 | not_the_printed_name / page | CINC Systems 1475 Holdings, LLC | 6,087,000 | CINC Systems 1475 Holdings, LLC | 1475 Holdings, LLC | 1475 Holdings, LLC / First Lien Secured Debt - Term Loan / S+525, 0.75% Floor / 01/18/2030 / 6,254 / 6,181 / 6,087 / (4)(9)(15) |
| 8 | Apollo Debt Solutions BDC 2026-03-31 | not_the_printed_name / page | United Flow Technologies Uft Buyer LLC | 67,645,000 | United Flow Technologies Uft Buyer LLC | Uft Buyer LLC | Uft Buyer LLC / First Lien Secured Debt - Term Loan / S+225 Cash plus 2.75% PIK, 0.50% PIK / 12/06/2032 / 68,328 / 67,674 / 67,645 / (4)(16) |
| 9 | BlackRock Private Credit Fun... 2024-12-31 | not_the_printed_name / page | Technology PointClickCare Technologies Inc. (Canad... | 1,600,693 | Technology PointClickCare Technologies Inc. (Canada) | PointClickCare Technologies Inc. (Canada) | PointClickCare Technologies Inc. (Canada) / First Lien Term Loan / SOFR(Q) / — / 3.25 / % / 7.58 / % / 10/16/2031 / $ / 1,588,777 / 1,589,002 / 1,600,693 / 0.15 / % / C |
| 10 | New Mountain Private Credit ... 2025-09-30 | not_the_printed_name / page | Notorious Topco, LLC | 26,051,000 | Notorious Topco, LLC | Consumer Products | Consumer Products / First Lien(2)(4) / SOFR(Q)(13)* / + / 4.75% +2.50%/PIK / 11.73% / 11/2021 / 11/2027 / 41,608 / 41,480 / 26,051 |

## unit_count_differs_from_row_text

**Overlap with existing rules.** None on value. Oracle C04 requires 70 pct of a fund-quarter's equity rows to carry any unit count (presence only); F11 checks the sign. field_coverage_drop ('unit count on equity') looks at the share carrying a count against the prior quarter. A wrong count published by the shared normaliser satisfies all three.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001287750 | ARES CAPITAL CORP | rg1b | 194 | 16 | 4423.7 | proxy_count_not_on_row:186; labelled_count_differs:6; labelled_count_not_published:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 45 | 14 | 1053.6 | proxy_count_not_on_row:45 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 60 | 16 | 195.1 | proxy_count_not_on_row:60 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 22 | 9 | 66.2 | proxy_count_not_on_row:22 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 33 | 14 | 60.0 | proxy_count_not_on_row:33 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 25 | 9 | 55.3 | proxy_count_not_on_row:25 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 8 | 7 | 31.5 | labelled_count_differs:6; labelled_count_not_published:2 |
| 0001849894 | MSD Investment Corp. | rg2 | 1 | 1 | 27.6 | proxy_count_not_on_row:1 |
| 0001869453 | Blue Owl Technology Income Corp. | rg2 | 1 | 1 | 14.7 | proxy_count_not_on_row:1 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 6 | 3 | 10.4 | proxy_count_not_on_row:6 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 3 | 3 | 8.5 | proxy_count_not_on_row:3 |
| 0001872371 | Oaktree Strategic Credit Fund | rg1b | 4 | 2 | 6.7 | proxy_count_not_on_row:4 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 7 | 3 | 6.2 | proxy_count_not_on_row:7 |
| 0001976336 | Antares Private Credit Fund | atxc | 1 | 1 | 5.4 | proxy_count_not_on_row:1 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 2 | 1 | 4.8 | labelled_count_not_published:2 |
| 0001899017 | Bain Capital Private Credit | bnxd | 1 | 1 | 3.9 | proxy_count_not_on_row:1 |
| 0001916099 | Diameter Credit Co | dixc | 1 | 1 | 1.3 | labelled_count_differs:1 |
| 0001950976 | 26North BDC, Inc. | tnxc | 3 | 3 | 1.1 | proxy_count_not_on_row:3 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 13 | 10 | 1.1 | proxy_count_not_on_row:13 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 2 | 2 | 1.0 | proxy_count_not_on_row:2 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 1 | 1 | 1.0 | proxy_count_not_on_row:1 |
| 0001859919 | Barings Private Credit Corp | rg2 | 2 | 2 | 0.9 | labelled_count_differs:2 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 13 | 9 | 0.7 | labelled_count_not_published:7; labelled_count_differs:6 |
| 0001920145 | Goldman Sachs Private Credit Corp. | rg1b | 2 | 2 | 0.7 | proxy_count_not_on_row:2 |
| 0001885968 | T Series BDC LLC | tsxd | 1 | 1 | 0.3 | proxy_count_not_on_row:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 7 | 7 | 0.1 | labelled_count_differs:7 |
| 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. | viya | 1 | 1 | 0.0 | proxy_count_not_on_row:1 |

**Read of the samples below (agent, 2026-10-17; not a disposition).** 8 of 10 real: another row's count or a x1000/1000 shift (Ares Storm 3,297,791 for the printed 3,958; AthenaHealth 198,505 for 10,487,951; BCRED Point Broadband 12,870 for 147,380; Sixth Street SMA 244 for 173,048). 2 unclear: BCRED Genstar 'Blocker Note' (a note classed equity; its printed 159,782 is a par, so no count applies but the published 1,041 is not printed either) and HPS BCPE Virginia (published 2,000,000 for a printed 2,000: a thousands scale, not decidable from the row). Almost all flags are shares_held_source 'derived_proxy': the shared normaliser (with_shares_fix) is the cause, as the observations say.

Sample of 10 flagged rows, seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2023-12-31 | proxy_count_not_on_row / page | Storm Investment S.a.r.l. | 200,000 | 3297791.0 (derived_proxy) | figures: 6.0; 2021.0; 3958.0; 0.2; 2.0; 6.0 | Ordinary shares / 06/2021 / 3,958 / — / 0.2 / (2)(6) |
| 2 | ARES CAPITAL CORP 2025-06-30 | proxy_count_not_on_row / page | AthenaHealth Group Inc., Minerva Holdco, Inc. and ... | 14,500,000 | 198505.0 (derived_proxy) | figures: 2.0; 2022.0; 10487951.0; 10.5; 14.5; 2.0 | Class A units / 02/2022 / 10,487,951 / 10.5 / 14.5 / (2) |
| 3 | AB Private Credit Investors ... 2025-09-30 | proxy_count_not_on_row / page | SCP-RESONETICS AGGREGATOR I, LLC | 33,748 | 541.0 (derived_proxy) | figures: 32450.0; 171840.0; 33748.0; 11.0 | SCP-RESONETICS AGGREGATOR I, LLC / Class B Common Units / Healthcare / 32,450 / 171,840 / 33,748 / (11) |
| 4 | Blackstone Private Credit Fu... 2023-12-31 | proxy_count_not_on_row / page | Point Broadband Holdings, LLC | 995,000 | 12870.0 (derived_proxy) | figures: 4.0; 147380.0; 420.0; 995.0; 0.0 | Point Broadband Holdings, LLC - Class Additional A Units / (4) / 147,380 / 420 / 995 / 0.00 |
| 5 | Blackstone Private Credit Fu... 2024-06-30 | proxy_count_not_on_row / page | Point Broadband Holdings, LLC | 528,000 | 12870.0 (derived_proxy) | figures: 4.0; 147380.0; 420.0; 528.0; 0.0 | Point Broadband Holdings, LLC - Class Additional A Units / (4) / 147,380 / 420 / 528 / 0.00 |
| 6 | Blackstone Private Credit Fu... 2025-06-30 | proxy_count_not_on_row / page | Point Broadband Holdings, LLC | 2,482,000 | 2766.0 (derived_proxy) | figures: 4.0; 685760.0; 1955.0; 2482.0; 0.01 | Point Broadband Holdings, LLC - Class B Common Units / (4) / 10/1/2021 / 685,760 / 1,955 / 2,482 / 0.01 |
| 7 | Blackstone Private Credit Fu... 2025-06-30 | proxy_count_not_on_row / page | Genstar Neptune Blocker, LLC | 160,000 | 1041.0 (derived_proxy) | figures: 4.0; 159782.0; 160.0; 160.0; 0.0 | Genstar Neptune Blocker, LLC - Blocker Note / (4) / 12/2/2024 / 159,782 / 160 / 160 / 0.00 |
| 8 | Blackstone Private Credit Fu... 2025-12-31 | proxy_count_not_on_row / page | Genstar Neptune Blocker, LLC | 160,000 | 1041.0 (derived_proxy) | figures: 4.0; 159782.0; 160.0; 160.0; 0.0 | Genstar Neptune Blocker, LLC - Blocker Note / (4) / 12/2/2024 / 159,782 / $ / 160 / $ / 160 / 0.00 / % |
| 9 | HPS Corporate Lending Fund 2025-12-31 | proxy_count_not_on_row / page | BCPE Virginia HoldCo, Inc. | 2,691,000 | 2000000.0 (derived_proxy) | figures: 4.0; 22.0; 2000.0; 1960.0; 2691.0 | BCPE Virginia Holdco, Inc. (4)(22) - Preferred Stock / 2,000 / 1,960 / 2,691 |
| 10 | Sixth Street Lending Partner... 2025-12-31 | labelled_count_differs / page | SMA Technologies Holdings, LLC | 18,000 | 244.0 (derived_proxy) | 173048.0; 173048.0 | Class B Units (173,048 units) / 11/21/2022 / 10 / 18 / 0.0 / % |

## pik_printed_not_published

**Overlap with existing rules.** None. C116/C117 check that a published pik_rate parses and lies in 0-20; pik_status's pik_terms proxy reads the published pik_rate. Nothing reads the PIK figure on the printed row or in the terms text, so a row with no PIK tag publishes no PIK and no rule fires.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001287750 | ARES CAPITAL CORP | rg1b | 65 | 14 | 2027.6 | pik_printed_not_published:52; pik_value_mismatch:13 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 36 | 9 | 224.8 | pik_printed_not_published:36 |
| 0001859919 | Barings Private Credit Corp | rg2 | 8 | 6 | 207.5 | pik_printed_not_published:7; pik_value_mismatch:1 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 15 | 4 | 198.5 | pik_printed_not_published:15 |
| 0001572694 | Goldman Sachs BDC, Inc. | gsxf | 7 | 2 | 132.8 | pik_printed_not_published:4; pik_value_mismatch:3 |
| 0001633336 | Crescent Capital BDC, Inc. | ccza | 39 | 12 | 93.3 | pik_printed_not_published:35; pik_value_mismatch:4 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 5 | 5 | 92.5 | pik_printed_not_published:5 |
| 0001278752 | MidCap Financial Investment Corp | mfxi | 24 | 10 | 90.1 | pik_printed_not_published:20; pik_value_mismatch:4 |
| 0001901164 | T. Rowe Price OHA Select Private Credit Fund | trxd | 10 | 3 | 83.3 | pik_printed_not_published:10 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 6 | 2 | 58.2 | pik_printed_not_published:6 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 2 | 2 | 39.1 | pik_printed_not_published:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 6 | 4 | 7.5 | pik_value_mismatch:6 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 7 | 3 | 3.0 | pik_value_mismatch:6; pik_printed_not_published:1 |
| 0001976336 | Antares Private Credit Fund | atxc | 1 | 1 | 2.8 | pik_printed_not_published:1 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 1 | 1 | 2.6 | pik_printed_not_published:1 |
| 0001916099 | Diameter Credit Co | dixc | 1 | 1 | 1.9 | pik_printed_not_published:1 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 1 | 1 | 1.8 | pik_printed_not_published:1 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 5 | 3 | 1.7 | pik_printed_not_published:3; pik_value_rounding:2 |
| 0001899017 | Bain Capital Private Credit | bnxd | 1 | 1 | 1.6 | pik_printed_not_published:1 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 2 | 2 | 0.5 | pik_value_rounding:1; pik_printed_not_published:1 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 1 | 1 | 0.3 | pik_printed_not_published:1 |
| 0001913724 | TPG Twin Brook Capital Income Fund | rg2 | 2 | 1 | 0.1 | pik_printed_not_published:2 |

**Read of the samples below (agent, 2026-10-17; not a disposition).** Printed-not-published: 9 of 10 real (Ares 'Senior preferred stock 10.00% PIK', HPS 'Foundation Automotive SF + 7.75% PIK', Crescent 'E + 1000 PIK'); 1 unclear (Crescent iLending, basis member_page_silent: the member says PIK, the printed row prints no rate at all). Mismatch: 8 of 10 real: pik_rate holds the floor (MidCap KLO 1.00 and HomeRenew 2.50 for 'SOFR+650 PIK, 2.50% Floor'; AB Single Digits 1.00), the spread (Blue Owl Kaseya 6.25 for '6.25% (2.50% PIK)') or the all-in coupon (Ares PRG 12.88 for '12.88% (3.13% PIK)'); 2 unclear (Crescent BioAgilytix 0.75 vs 2.75, AB American Physician 3.5 vs 3.0). Tags rounded to one decimal are their own kind, pik_value_rounding (3 rows).

Sample of 10 flagged rows (kind pik_printed_not_published), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2022-09-30 | pik_printed_not_published / page | Cehntric Brands LLC and Centric Brands GP LLC | 71,200,000 |  | 11.8 | First lien senior secured loan / 11.80% PIK / SOFR (Q) / 9.00% / 10/2018 / 10/2025 / 74.2 / 74.1 / 71.2 / (2)(11) |
| 2 | ARES CAPITAL CORP 2024-12-31 | pik_printed_not_published / page | Visual Edge Technology, Inc. | 45,100,000 |  | 10.0 | Senior preferred stock / 10.00% PIK / 07/2023 / 4,737 / 47.2 / 45.1 / (2) |
| 3 | ARES CAPITAL CORP 2024-12-31 | pik_printed_not_published / page | LifeStyles Bidco Ltd., Lifestyles US Holdco, Inc. ... | 3,700,000 |  | 8.0 | Preferred units / 8.00% PIK / 11/2022 / 3,178 / 3.7 / 3.7 / (2)(6) |
| 4 | ARES CAPITAL CORP 2025-03-31 | pik_printed_not_published / page | BCTO Ignition Purchaser, Inc. | 4,100,000 |  | 12.79 | BCTO Ignition Purchaser, Inc. / Enterprise software provider / Senior subordinated loan / 12.79% PIK / SOFR (Q) / 8.50% / 04/2023 / 10/2030 / 4.1 / 4.1 / 4.1 / (2)(10) |
| 5 | ARES CAPITAL CORP 2025-12-31 | pik_printed_not_published / page | Balrog Acquisition, Inc., Balrog Topco, Inc. and B... | 30,000,000 |  | 11.0 | Series A preferred shares / 11.00% PIK / 09/2021 / 08/2051 / 21,921 / 35.3 / 30.0 / (2) |
| 6 | Crescent Capital BDC, Inc. 2023-06-30 | pik_printed_not_published / page | AX VI INV2 Holding AB (Voff) | 2,107,000 |  | 10.0 | AX VI INV2 Holding AB (Voff) (6)(11) / Senior Secured Second Lien Term Loan / E + 1000 PIK / 13.23% / 08/2030 / € / 1,931 / 1,902 / 0.3 / 2,107 |
| 7 | Crescent Capital BDC, Inc. 2024-12-31 | pik_printed_not_published / member_page_silent | iLending LLC | 2,407,000 |  | 2.0 | iLending LLC (9) / Senior Secured First Lien Term Loan / 06/2026 / 4,385 / 4,385 / 0.3 / 2,407 |
| 8 | HPS Corporate Lending Fund 2025-03-31 | pik_printed_not_published / page | Foundation Automotive US Corp | 10,095,000 |  | 7.75 | Foundation Automotive US Corp (4)(7)(18) / SF + / 7.75% PIK / 12/24/2027 / 18,779 / 18,571 / 10,095 |
| 9 | HPS Corporate Lending Fund 2025-03-31 | pik_printed_not_published / page | Club Car Wash Preferred, LLC | 8,817,000 |  | 15.0 | Club Car Wash Preferred, LLC (4)(21) - Preferred Stock / 15.00% PIK / 15.00% / 8,817 / 8,817 / 8,817 |
| 10 | ARES STRATEGIC INCOME FUND 2025-12-31 | pik_printed_not_published / page | JAMS Holdings LP and Jams Buyer LLC | 1,342,400 |  | 8.0 | Preferred units / 8.00% PIK / 06/2025 / 982,000 / 1,028.3 / 1,342.4 / (2)(13) |

Sample of 10 flagged rows (kind pik_value_mismatch, reported separately), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | MidCap Financial Investment ... 2023-03-31 | pik_value_mismatch / page | KLO Holdings, LLC 1244311 B.C. Ltd. | 1,093,000 | 1.0 | 5.0 | First Lien Secured Debt / L+500 PIK, 1.00% Floor / 09/30/25 / 1,158 / 1,158 / 1,093 / (17)(28) |
| 2 | MidCap Financial Investment ... 2025-06-30 | pik_value_mismatch / page | HomeRenew Buyer, Inc. | 3,192,000 | 2.5 | 6.5 | HomeRenew Buyer, Inc. / First Lien Secured Debt - Term Loan / SOFR+650 PIK, 2.50% Floor / 04/14/30 / 3,192 / 3,192 / 3,192 / (9)(31) |
| 3 | ARES CAPITAL CORP 2024-09-30 | pik_value_mismatch / page | Production Resource Group, L.L.C. and PRG III, LLC | 15,600,000 | 12.879999999999999 | 3.13 | First lien senior secured loan / 12.88% (3.13% PIK) / SOFR (Q) / 8.13% / 07/2020 / 08/2029 / 15.6 / 15.5 / 15.6 / (2)(11) |
| 4 | ARES CAPITAL CORP 2025-03-31 | pik_value_mismatch / page | Radiant Intermediate Holding, LLC | 1,800,000 | 10.41 | 3.0 | Radiant Intermediate Holding, LLC / Provider of HVAC, plumbing and electrical services / First lien senior secured loan / 10.41% (3.00% PIK) / SOFR (Q) / 6.00% / 04/2023 / 11/2026 / 2.1 / 2.1 / 1.8 / (2)(10) |
| 5 | Goldman Sachs BDC, Inc. 2023-06-30 | pik_value_mismatch / member | SPay, Inc. (dba Stack Sports) | 2,145,000 | 9.25 | 3.5 | member: Investment 1st Lien/Senior Secured Debt - 198.48% SPay, Inc. (dba Stack Sports) Industry Interactive Media & Services Interest Rate 14.46% Reference Rate and Spread S + 9.25% (incl. 3.50% PIK) Maturit... ; page: 27 1,900 ( 31 ) ( 33 ) (6) (7) (8) (11) SPay, Inc. (dba Stack Sports) Interactive Media & Services 14.45 % S +... |
| 6 | Crescent Capital BDC, Inc. 2023-03-31 | pik_value_mismatch / member | BioAgilytix (5) | 527,000 | 0.75 | 2.75 | member: Investments United States Debt Investments Pharmaceuticals, Biotechnology & Life Sciences BioAgilytix (5) Investment Type Senior Secured First Lien Delayed Draw Term Loan Interest Term L + 625 (75 Flo... ; page: euticals, Biotechnology & Life Sciences BioAgilytix (5) Investment Type Senior Secured First Lien Delayed Draw... |
| 7 | AB Private Credit Investors ... 2023-12-31 | pik_value_mismatch / page | Single Digits, Inc | -54,099 | 1.0 | 3.0 | Single Digits, Inc.(2) (6) / Digital Infrastructure & Services / Revolver / 9.85% (S + 4.25%; 3.00% PIK; 1.00% Floor) / 06/19/2026 / — / (1,411 / ) / (54,099 / ) |
| 8 | AB Private Credit Investors ... 2025-12-31 | pik_value_mismatch / member | American Physician Partners, LLC | 0 | 3.5000000000000004 | 3.0 | member: US Corporate Debt / 1st Lien/Senior Secured Debt / American Physician Partners, LLC / Healthcare / Delayed Draw Term Loan / —% (S + 6.75%; 1.00% Floor; 3.00% PIK) / 3/31/2026 ; page: 2030 1,321,971 1,310,950 1,302,141 (15) American Physician Partners, LLC Healthcare Term Loan - ( S + 6.75 %; 1.00 % Floor; 3.00 % PIK) 3/3... |
| 9 | Blue Owl Credit Income Corp. 2023-09-30 | pik_value_mismatch / page | Kaseya Inc. | 265,000 | 6.25 | 2.5 | Kaseya Inc.(7)(17)(19) / First lien senior secured delayed draw term loan / SR + / 6.25% (2.50% PIK) / 06/2024 / 265 / 227 / 265 / 0.0 / % |
| 10 | Blue Owl Credit Income Corp. 2023-12-31 | pik_value_mismatch / page | Kaseya Inc. | 266,000 | 6.25 | 2.5 | Kaseya Inc.(7)(15)(17) / First lien senior secured delayed draw term loan / SR + / 6.25% (2.50% PIK) / 06/2024 / 267 / 231 / 266 / 0.0 / % |

## industry_not_published

**Overlap with existing rules.** Partial. field_coverage_drop ('filer industry', extracted_industry) fires on a fall of 20 points against the fund's previous quarter with 20+ funded rows; it is blind to a fund's first quarters (Golub 2023, Stone Point 2023-24) and to a gap that never closes (Guardian IV). It also reads extracted_industry, while the public sector partition reads gics_sub_industry (pipeline/public_partitions.py). This candidate reads gics_sub_industry and reports both.

Coverage distribution, fund-quarters with 20+ funded rows (n = 608 of 619):

| coverage below | gics_sub_industry (published) | extracted_industry (filer) |
|---|---:|---:|
| 0.50 | 9 | 85 |
| 0.80 | 57 | 87 |
| 0.90 | 118 | 109 |
| 0.95 | 152 | 134 |
| 0.98 | 196 | 150 |
| 0.99 | 233 | 161 |
| 1.00 | 283 | 220 |

gics_sub_industry coverage percentiles: p05 0.707, p10 0.805, p25 0.951, median 1.000. Threshold used for the flagged rows below: 0.80 (proposed; see the reply).

Lowest 15 fund-quarters:

| cik | fund | quarter | funded rows | gics coverage | extracted coverage | FV without gics (M) |
|---|---|---|---:|---:|---:|---:|
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-06-30 | 65 | 0.015 | 0.000 | 481.9 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-09-30 | 94 | 0.032 | 0.000 | 672.0 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2026-06-30 | 121 | 0.041 | 0.000 | 1418.3 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2026-03-31 | 107 | 0.047 | 0.000 | 1355.3 |
| 0002049733 | Blackstone Private Real Estate Credit & ... | 2025-12-31 | 113 | 0.053 | 0.000 | 912.9 |
| 0002012139 | Fortress Private Lending Fund | 2025-06-30 | 39 | 0.205 | 0.051 | 288.0 |
| 0001742313 | Monroe Capital Income Plus Corp | 2023-09-30 | 382 | 0.314 | 0.003 | 1372.2 |
| 0001742313 | Monroe Capital Income Plus Corp | 2023-06-30 | 364 | 0.319 | 0.003 | 1207.1 |
| 0001742313 | Monroe Capital Income Plus Corp | 2023-03-31 | 344 | 0.331 | 0.003 | 1046.5 |
| 0002037804 | New Mountain Private Credit Fund | 2026-06-30 | 237 | 0.574 | 0.000 | 616.4 |
| 0001634452 | AB Private Credit Investors Corp | 2023-03-31 | 352 | 0.608 | 0.000 | 379.3 |
| 0001634452 | AB Private Credit Investors Corp | 2023-06-30 | 363 | 0.609 | 0.000 | 414.6 |
| 0001925531 | New Mountain Guardian IV BDC, L.L.C. | 2026-06-30 | 294 | 0.633 | 0.014 | 702.4 |
| 0002037804 | New Mountain Private Credit Fund | 2026-03-31 | 237 | 0.633 | 0.000 | 569.9 |
| 0002037804 | New Mountain Private Credit Fund | 2025-12-31 | 241 | 0.635 | 0.000 | 567.8 |

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001838126 | HPS Corporate Lending Fund | rg1b | 634 | 5 | 8983.6 | no_industry_at_all:634 |
| 0001837532 | Apollo Debt Solutions BDC | rg1b | 156 | 1 | 6915.1 | no_industry_at_all:156 |
| 0002049733 | Blackstone Private Real Estate Credit & Incom... | brxb | 480 | 5 | 4840.4 | no_industry_at_all:480 |
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

**Read of the samples below (agent, 2026-10-17; not a disposition).** 10 of 10 are funded rows with no published industry. New Mountain (Guardian IV, Private Credit, NMF SLF) and Stone Point print the heading on the page and the build does not read it; HPS rows print no industry on the row and the GICS name cache has no entry. All are real gaps in the field; whether a gap is an error to fix or a coverage limit is the owner's call.

Sample of 10 flagged rows, seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | NMF SLF I, Inc. 2025-09-30 | no_industry_at_all / coverage | Notorious Topco, LLC | 1,155,000 |  |  | First Lien(3) / SOFR(Q)(11) / 6.75% / 11.01% / 11/2021 / 05/2027 / 1,844 / 1,839 / 1,155 |
| 2 | Stone Point Credit Corp 2024-06-30 | no_industry_at_all / coverage | One Call Corporation | 15,660,460 |  |  | One Call Corporation / ​ / First Lien Term Loan / ​ / (8)(10) / ​ / SOFR + / 5.50 / %, / 0.75 / % Floor / ​ / 11.09 / % / 4/22/2027 / ​ / 16,457,584 / ​ / 15,664,042 / ​ / 15,660,460 / ​ / 1.3 / % |
| 3 | HPS Corporate Lending Fund 2025-03-31 | no_industry_at_all / coverage | LC Ahab US Bidco LLC | 5,046,000 |  |  | LC Ahab US Bidco LLC (4)(7) / SF + / 3.00% / 7.32 / % / 5/1/2031 / 5,078 / 5,063 / 5,046 |
| 4 | HPS Corporate Lending Fund 2025-06-30 | no_industry_at_all / coverage | Yes Energy LLC | 25,683,000 |  |  | Yes Energy LLC (4)(10) / SF + / 5.00% / 9.33 / % / 4/21/2028 / 25,683 / 25,335 / 25,683 |
| 5 | HPS Corporate Lending Fund 2025-06-30 | no_industry_at_all / coverage | PF Finco PTY LTD | 26,950,000 |  |  | PF Finco PTY LTD (4)(5)(10) / B + / 6.25% / 10.07 / % / 5/30/2030 / AUD / 41,852 / 26,381 / 26,950 |
| 6 | HPS Corporate Lending Fund 2025-09-30 | no_industry_at_all / coverage | Saga Mid Co Limited | 79,000 |  |  | Saga Mid Co Limited (4)(5)(6)(10) / 2/27/2031 / GBP / 30,110 / (901) / 79 |
| 7 | New Mountain Guardian IV BDC... 2025-09-30 | no_industry_at_all / coverage | Kele Holdco, Inc. | 1,355,000 |  |  | Distribution & Logistics / First Lien(4)(8) / SOFR(M) / + / 4.50% / 8.66% / 07/2025 / 02/2028 / 1,355 / 1,355 / 1,355 |
| 8 | New Mountain Guardian IV BDC... 2025-12-31 | no_industry_at_all / coverage | KENG Acquisition, Inc. | 65,000 |  |  | First Lien(8)(9) - Drawn / SOFR(Q) / + / 4.50% / 8.34% / 01/2025 / 08/2029 / 65 / 65 / 65 |
| 9 | New Mountain Private Credit ... 2026-03-31 | no_industry_at_all / coverage | TMK Hawk Parent, Corp. | 3,795,000 |  |  | Distribution & Logistics / First Lien(2)(4) / SOFR(M) / + / 4.00% / 7.67% / 01/2024 / 07/2029 / $ / 5,874 / $ / 5,874 / $ / 3,795 |
| 10 | New Mountain Private Credit ... 2026-06-30 | no_industry_at_all / coverage | The Ultimus Group Midco, LLC. | 5,696,000 |  |  | Financial Services & Technology / First Lien(4) / SOFR(Q) / + / 4.50% / 8.23% / 07/2025 / 07/2032 / 5,725 / 5,699 / 5,696 / 0.60 / % |

## preferred_published_as_common

**Overlap with existing rules.** Partial. Column rule X01 flags a PRIVATE_EQUITY row not classed PREFERRED_EQUITY with interest_rate > 0, so it catches a dividend rate on a common row but not a PIK-only rate (Commonwealth LNG, KWOR publish pik_rate and no interest_rate) and never the text. Oracle C05 is a global share of rows whose instrument text says common and carry a rate. No rule reads 'preferred' on the printed row against the class.

Per fund (flagged funds only):

| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |
|---|---|---|---:|---:|---:|---|
| 0001287750 | ARES CAPITAL CORP | rg1b | 177 | 16 | 2163.1 | rate_on_common:174; text_and_rate:3 |
| 0001803498 | Blackstone Private Credit Fund | rg1b | 5 | 4 | 1823.8 | text_says_preferred:3; rate_on_common:2 |
| 0001812554 | Blue Owl Credit Income Corp. | rg1b | 23 | 14 | 787.1 | rate_on_common:14; text_and_rate:9 |
| 0001925309 | Sixth Street Lending Partners | rg1b | 7 | 7 | 374.2 | text_says_preferred:7 |
| 0001702510 | Carlyle Credit Solutions, Inc. | ccxd | 30 | 4 | 192.2 | rate_on_common:30 |
| 0001918712 | ARES STRATEGIC INCOME FUND | rg1b | 52 | 12 | 152.6 | rate_on_common:52 |
| 0001742313 | Monroe Capital Income Plus Corp | rg2 | 82 | 13 | 127.5 | rate_on_common:82 |
| 0001838126 | HPS Corporate Lending Fund | rg1b | 14 | 4 | 88.3 | rate_on_common:14 |
| 0001508655 | Sixth Street Specialty Lending, Inc. | ssxf | 16 | 7 | 49.9 | text_says_preferred:9; rate_on_common:7 |
| 0001634452 | AB Private Credit Investors Corp | abxf | 101 | 14 | 46.2 | text_says_preferred:101 |
| 0001851322 | North Haven Private Income Fund LLC | rg2 | 13 | 6 | 27.4 | text_and_rate:9; text_says_preferred:3; rate_on_common:1 |
| 0001930087 | Golub Capital Private Credit Fund | rg1b | 3 | 3 | 10.8 | text_and_rate:2; text_says_preferred:1 |
| 0001859919 | Barings Private Credit Corp | rg2 | 18 | 13 | 8.0 | rate_on_common:18 |
| 0001989817 | HPS Corporate Capital Solutions Fund | hcxe | 1 | 1 | 4.3 | rate_on_common:1 |
| 0001993402 | Antares Strategic Credit Fund | rg2 | 1 | 1 | 2.9 | rate_on_common:1 |
| 0001930679 | KKR FS Income Trust | kfxh | 1 | 1 | 2.0 | rate_on_common:1 |
| 0001976336 | Antares Private Credit Fund | atxc | 1 | 1 | 1.1 | rate_on_common:1 |
| 0001885968 | T Series BDC LLC | tsxd | 1 | 1 | 0.0 | rate_on_common:1 |

**Read of the samples below (agent, 2026-10-17; not a disposition).** rate_on_common (399 of 546) is mostly not evidence of preferred: of its 10 samples 9 are units the filer does not call preferred but which carry a PIK or fixed dividend (Ares 'Class A units 8.00% PIK', Monroe NationsBenefits 'Series B units 5.00% PIK', Sixth Street 'Class AA Units 20.00%', Ares CFC 'Loan instrument units 9.75% PIK'); outside the sample BCRED Port Arthur LNG 'Class B Units 7.60% PIK' (1,079M) is the same shape. 1 is a loan published as common equity (HPS DCA Acquisition '13.13% PIK', maturity 12/28/2032; HPS Foundation Automotive 'SF + 7.75% PIK' is another), a real class error but not a preferred one. The text kinds are stronger: 10 of 10 text samples read as preferred published as common (9 AB Private Credit venture rows filed under 'U.S. Preferred Stock', Series C-1 to G; Golub Eclipse 'Preferred stock'), but the sample is 90 pct one fund. Outside it: Ares McLaren 'Senior preference shares', Blue Owl Metis 'Series A Convertible Preferred Stock'. rate_on_common needs an owner ruling on PIK-dividend units first.

Sample of 10 flagged rows (text kinds: text_says_preferred, text_and_rate), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | AB Private Credit Investors ... 2023-03-31 | text_says_preferred / member | Netskope Inc | 382,208 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series G | member: Netskope Inc - U.s.preferred Stock At Two Point Zero Three Percentage - Series G ; (issuer's first words not found on the visible page) |
| 2 | AB Private Credit Investors ... 2023-06-30 | text_says_preferred / member | Datarobot Inc | 329,334 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series E | member: Datarobot Inc One - U.s.Preferred Stock At Two Point Zero Two Percentage - Series E ; (issuer's first words not found on the visible page) |
| 3 | AB Private Credit Investors ... 2023-06-30 | text_says_preferred / member | Heap Inc. | 148,936 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series D | member: Heap Inc.One - U.s.Preferred Stock At Two Point Zero Two Percentage - Series D ; (issuer's first words not found on the visible page) |
| 4 | AB Private Credit Investors ... 2024-06-30 | text_says_preferred / member | Content Square SAS | 206,715 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Ordinary Shares | Content Square SAS(9) (11) / Series F / Software & Tech Services / 11/30/2023 / 24,472 / 206,755 / 206,715 |
| 5 | AB Private Credit Investors ... 2024-06-30 | text_says_preferred / member | Datarobot, Inc. | 242,464 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series E | Datarobot, Inc.(11) / Series E / Software & Tech Services / 8/31/2019 / 38,190 / 289,278 / 242,464 |
| 6 | AB Private Credit Investors ... 2024-09-30 | text_says_preferred / member | Degreed, Inc. | 193,286 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series C-1 | Degreed, Inc. / Series C-1 / Software & Tech Services / 6/19/2019 / 43,819 / 278,541 / 193,286 |
| 7 | AB Private Credit Investors ... 2024-09-30 | text_says_preferred / member | Vectra AI, Inc. | 113,970 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series F | Vectra AI, Inc. / Series F / Software & Tech Services / 5/28/2021 / 17,064 / 131,095 / 113,970 |
| 8 | AB Private Credit Investors ... 2025-06-30 | text_says_preferred / member | Datarobot, Inc. | 48,854 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series F | Datarobot, Inc. / Series F / Software & Tech Services / 10/27/2020 / 6,715 / 88,248 / 48,854 |
| 9 | AB Private Credit Investors ... 2026-03-31 | text_says_preferred / member | Datarobot, Inc. | 36,075 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Series F | Datarobot, Inc. / Series F / Software & Tech Services / 10/27/2020 / 6,715 / 88,248 / 36,075 |
| 10 | Golub Capital Private Credit... 2026-06-30 | text_says_preferred / member | Eclipse Buyer, Inc. | 2,902,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate= | Preferred stock | member: Eclipse Buyer, Inc. / Preferred stock ; page: 5.00 % (i) 8.67 % 09/2028 240 237 - 236 Eclipse Buyer, Inc.*^ One stop SF + 4.50 % (i) 8.15 % 09/2031 12,644 12,550 0.3 12,391 Eclipse Buyer, Inc.^(5) One stop N/A(6) 09/2031 - ( 46 ) - ( 32 ) Eclipse Buyer, Inc.^(5) One stop N/A(6) 09/2031 - ( 8 ) - ( 43 ) Eisner Advisory Gr... |

Sample of 10 flagged rows (kind rate_on_common), seed 20261017:

| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |
|---|---|---|---|---:|---|---|---|
| 1 | ARES CAPITAL CORP 2023-03-31 | rate_on_common / shape | Watermill Express, LLC and Watermill Express Holdi... | 3,600,000 | EQUITY_COMMON/COMMON_EQUITY pik=8.0 rate= | Class A units | Class A units / 8.00% PIK / 04/2021 / 282,200 / 3.3 / 3.6 |
| 2 | ARES CAPITAL CORP 2025-12-31 | rate_on_common / shape | CFC Funding LLC | 20,200,000 | EQUITY_COMMON/COMMON_EQUITY pik=9.75 rate= | Loan instrument units | CFC Funding LLC / SME-related SPV / Loan instrument units / 9.75% PIK / 07/2023 / 16,680 / 20.2 / 20.2 / (6) |
| 3 | ARES CAPITAL CORP 2025-12-31 | rate_on_common / shape | Denali Intermediate Holdings, Inc. and Denali Pare... | 5,400,000 | EQUITY_COMMON/COMMON_EQUITY pik=8.0 rate= | Series A units | Series A units / 8.00% PIK / 08/2025 / 540,800 / 5.6 / 5.4 / (2) |
| 4 | ARES CAPITAL CORP 2026-03-31 | rate_on_common / shape | PracticeTek Purchaser, LLC, PracticeTek MidCo, LLC... | 29,200,000 | EQUITY_COMMON/COMMON_EQUITY pik=8.0 rate= | Class A units | Class A units / 8.00% PIK / 03/2021 / 33,220,282 / 28.6 / 29.2 / (2) |
| 5 | Sixth Street Specialty Lendi... 2026-06-30 | rate_on_common / shape | TS Imagine, Inc. | 45,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate=20.0 | Class AA Units (19,093 units) Initial Acquisition Date 11/1/... | Class AA Units (19,093 units) / 11/1/2024 / 20.00 / % / 20.00 / % / 46 / 45 / 0.0 / % |
| 6 | Carlyle Credit Solutions, In... 2025-03-31 | rate_on_common / shape | NEFCO Holding Company LLC | 608,000 | EQUITY_COMMON/COMMON_EQUITY pik= rate=8.0 |  | NEFCO Holding Company LLC / (a) / (6) / Construction & Building / 8.00% / 8/5/2022 / 1 / 608 / 608 / 0.04 |
| 7 | Monroe Capital Income Plus C... 2023-03-31 | rate_on_common / shape | NationsBenefits, LLC | 2,824,000 | EQUITY_COMMON/COMMON_EQUITY pik=5.0 rate= | Equity Securities, Series B units | NationsBenefits, LLC (356,658 Series B units) (####) / ​ / n/a / ​ / n/a / ​ / 5.00 / % PIK / ​ / 8/20/2021 / ​ / — / ​ / — / ​ / ​ / 2,393 / ​ / ​ / 2,824 / ​ / 0.3 / % |
| 8 | Monroe Capital Income Plus C... 2026-03-31 | rate_on_common / shape | NationsBenefits, LLC | 5,289,000 | EQUITY_COMMON/COMMON_EQUITY pik=5.0 rate= | (Series B units) Equity Securities | NationsBenefits, LLC (369,827 Series B units) / (17) / n/a / n/a / 5.00% PIK / 8/20/2021 / — / — / 2,498 / 5,289 / 0.2 / % |
| 9 | HPS Corporate Lending Fund 2026-03-31 | rate_on_common / shape | DCA Acquisition Holdings LLC | 7,000 | EQUITY_COMMON/COMMON_EQUITY pik=13.13 rate= |  | DCA Acquisition Holdings LLC (4)(7)(19) / 13.13% PIK / 12/28/2032 / 132 / 111 / 7 |
| 10 | ARES STRATEGIC INCOME FUND 2025-06-30 | rate_on_common / shape | PCMI Parent, LLC and PCMI Ultimate Holdings, LP | 1,055,200 | EQUITY_COMMON/COMMON_EQUITY pik=9.0 rate= | Class A units | Class A units / 9.00% PIK / 03/2025 / 1,063 / 1,091.4 / 1,055.2 / (2)(12) |

