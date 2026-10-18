# v0.5 candidate rules: independent false-alarm review (2026-10-18)

Question: how often do the five candidate rules in `pipeline/candidate_rules.py` (measured in `v05_rule_candidates_2026-10-17.md`, commit 6751318) flag a row whose published value is actually right? Reviewer did not build the rules; rule code not modified.

Method. Pool: `v05_rule_candidates_2026-10-17_rows.csv`. Per rule, 30 flagged rows at random, seed 20261018, no fund supplying more than 6 (script `scripts/v05_evidence/candidate_rules_falsealarm_sample.py`). Each row's printed line was read in the cached filing (main checkout `data/raw/filings/bdc_html`, via `page_line.py` and the raw table rows) and labelled real_error / false_alarm / unclear. Rule 5 sampled from its text kinds only (owner 2026-10-18: PIK-dividend units are not preferred unless the filer calls them preferred, so the rate-only kind is dropped). Rule 4 judged per fund-quarter (30 fund-quarters, max 6 per fund, 3 flagged rows read each). Labels and scoring: `scripts/v05_evidence/candidate_rules_falsealarm_score.py`.

Files: `v05_rule_candidates_falsealarm_2026-10-18_labels.csv` (120 labelled rows, with pattern and note), `..._rule4_fq.csv` (30 fund-quarters), `..._rule1_blind.csv` (rule 1 blind spots, 627 fund-quarters).

Caveats. The fund cap makes the sample fund-balanced, not row-weighted; a row-weighted figure (each sampled row weighted by its fund's flagged rows / its fund's sample size) is given beside it. 30 rows gives wide intervals. "Real" means the published value differs from the page the way the rule claims; it does not say the fix is easy or that a clean row is correct.

## Precision

| rule | n | real | false | unclear | precision real/(real+false) | 95% Wilson | real/n (unclear as not real) | row-weighted |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| 1 issuer_name_differs_from_page | 30 | 20 | 9 | 1 | 0.69 | 0.51-0.83 | 0.67 | 0.93 |
| 2 unit_count_differs_from_row_text | 30 | 24 | 2 | 4 | 0.92 | 0.76-0.98 | 0.80 | 0.92 |
| 3 pik_printed_not_published | 30 | 26 | 3 | 1 | 0.90 | 0.74-0.96 | 0.87 | 0.97 |
| 5 preferred_published_as_common, text kinds | 30 | 29 | 0 | 1 | 1.00 | 0.88-1.00 | 0.97 | 1.00 |
| 4 industry_not_published (fund-quarters) | 30 | 25 printed (gap) | 5 not printed (limit) | 0 | 0.83 gap share | 0.66-0.93 | - | - |

By basis: rule 2's 24 page-basis rows are 24 real, 0 false, 4 unclear; both false alarms are member basis. Rule 3's 27 page-basis rows are 26 real, 1 false (the rounding kind); the other 2 false and 1 unclear are member / member_page_silent basis. Rule 1 is all page basis.

## Rule 1 issuer_name_differs_from_page

Real (20): group heading glued in front of the legal entity (7; Apollo 'Vantive Spruce Bidco II Inc.' where the page prints 'Vantive' on a heading row and 'Spruce Bidco II Inc.' on the row; MidCap 'KLO Holdings, LLC 1244311 B.C. Ltd'), industry appended or prefixed (6; Goldman Sachs PCC '... Commercial Services & Supplies', BlackRock 'Environmental, Maintenance and Security Services TruGreen'), instrument appended or used as the name (4; Ares 'Zeppelin ... First lien senior secured revolving loan', Oaktree 'CLO Notes'), footnote digit (T. Rowe 'Kaseya, Inc.4'), member typo (MSD 'USA Debunk' for 'Debusk'), member names another entity (MidCap equity in 'Wildcat Parent LP' published as 'Wildcat BuyerCo, Inc.').

False-alarm patterns (9):
- **New Mountain printed row starts at the industry cell (5, all NMF SLF I).** New Mountain prints the company on its own row and the industry in the first cell of the instrument row. The joined `printed_row` therefore starts 'Food & Beverage | First Lien ...'. The label filter uses the fund's `extracted_industry`, which the build does not read for New Mountain (see rule 4), so the industry cell survives as a "name cell". These are the leakage of a fund the rule is otherwise blind to (97 pct, below).
- **Page spelling variant on one row (2).** Antares 'ClearCapital' and 26North 'Ascend Partners' on the flagged row; sibling rows of the same filing print the published spelling.
- **Misjoined printed row (1).** Antares Southpaw joined to the Movati row; the page prints the published name.
- **Member carries a fuller legal name (1).** Bain 'IMA Financial Group LLC'; the page omits 'LLC'.

Unclear (1): Barings 'Fineline Technologies, Inc.' published, current row prints 'FineLine Systems' (prior period prints the published name; likely a rename).

The row-weighted precision (0.93) is high only because Apollo is 4,179 of the 6,537 flagged rows and its group-prefix rows are real. Whether the group-prefix convention is an error to fix is an owner question; it does break issuer matching across funds.

### Rule 1 blind spots

Rule 1 can test a row only when the page reader joined a printed row (`bdc_ixbrl_field_status`) and that row still has a name cell. Across the 627 fund-quarters of the accepted sandboxes (257,293 published rows with an issuer): 10,868 rows have no printed row and 47,744 have a printed row but no name cell. Blind share 22.8 pct of rows, 14.4 pct of absolute FV. 14 fund-quarters are fully blind (>= 99 pct), 96 are at least half blind.

| fund | fund-quarters | blind share (rows) | blind share (FV) | why |
|---|---:|---:|---:|---|
| New Mountain Guardian IV (0001925531) | 14 | 0.98 | 0.98 | company on its own row, no name cell on the instrument row |
| NMF SLF I (0001766037) | 14 | 0.97 | 0.95 | same |
| New Mountain Private Credit (0002037804) | 7 | 0.96 | 0.93 | same |
| Stepstone Private Credit (0001950803) | 12 | 0.95 | 0.91 | no name cell (instrument-first rows) |
| Lord Abbett (0002008748) | 8 | 0.80 | 0.80 | no printed row at all 2024-09-30 to 2026-03-31 (7 quarters fully blind); 2026-06-30 joined |
| Ares Capital (0001287750) | 16 | 0.59 | 0.59 | later tranches printed without the company |
| Trinity Capital (0001786108) | 14 | 0.54 | 0.38 | both causes |
| MidCap Financial (0001278752) | 14 | 0.52 | 0.17 | later tranches without the company |
| MSD (0001849894) | 13 | 0.43 | 0.15 | not comparable |
| Apollo Debt Solutions (0001837532) | 14 | 0.41 | 0.09 | later tranches without the company |
| Ares Strategic Income (0001918712) | 14 | 0.29 | 0.24 | later tranches |
| Sixth Street Lending Partners, Blue Owl Credit Income, KKR FS Income Trust Select, TSLX, Barings PCC, KKR FS Income Trust | 10-14 each | 0.21-0.26 | 0.02-0.29 | mix |

Other fully blind fund-quarters (no printed row): Goldman Sachs BDC 2023-03-31 and 2023-06-30, AB Private Credit Investors 2023-03-31 and 2023-06-30, Goldman Sachs PMMC II 2023-03-31 and 2023-06-30, Goldman Sachs PCC 2023-06-30. Per fund-quarter detail in `..._rule1_blind.csv`. A clean rule-1 result on these fund-quarters means "not looked at", not "names right". Later-tranche rows are a design limit: their company sits on the first tranche's row, which the rule does test.

## Rule 2 unit_count_differs_from_row_text

Real (24): another row's count on this row (10; BCRED Point Broadband Class B carries Class A's 15,636; Crescent ACI preferred carries the common's 907,499; HPS ONE Group A-2 carries B-2's 6,667), a derived proxy count printed nowhere on the row (10), x1000 (2; 26North FH DMI 400,429,000 for 400,429), labelled count not published (2).

False alarms (2), both member basis: a digit in the issuer name read as a count (Diameter 'VCI Asset Holdings 1 LLC Class B Interests' = 1 interest; published 1,237 is the page figure), and a warrant's 'up to 3,280,444 shares' in the member against the page's 3,223,122 (Ares PFL; published = page).

Unclear (4): HPS units scale (2; 'Par Amount/Units' 6,312 and 2,000 vs published x1000, the schedule does not say whether units are in thousands), Bain Legacy '4' in the Principal/Share column of an in-thousands schedule, Goldman Sachs PCC member naming FS WhiteWater while the row's FV and date are the RPC ABC row.

## Rule 3 pik_printed_not_published

Real (26): PIK printed and not published (21, Ares preferred and units, Barings Rocade, Crescent 'including 50 PIK', HPS, T. Rowe, Carlyle), pik_rate holds the floor (4, MidCap 'SOFR+650 PIK, 2.50% Floor' published 2.5, AB Single Digits 1.0), pik_rate holds the all-in coupon (1, Ares Convey 9.65 for 4.25% PIK).

False alarms (3): the member text disagrees with the page and the published value follows the page (2; AB American Physician member 3.00% PIK, page 3.50% = published; Diameter BVI member '(5.00% PIK)', page DDTL row prints no PIK); kind pik_value_rounding (1; Antares Vertex 3.8 for 3.83, filer tag precision). Unclear (1): Crescent Lighthouse, member '(plus 75 PIK)', visible row prints no PIK.

## Rule 4 industry_not_published (fund-quarter level)

25 of 30 sampled fund-quarters print the industry on the page and the build does not publish it (a gap we could fill): New Mountain Private Credit, Guardian IV and NMF SLF (industry cell under each company), Monroe, Stone Point, HPS Corporate Lending, HPS Capital Solutions, Apollo 2026-06-30 (industry section headings), AB Private Credit Investors (industry on every row), Trinity (headings printed; its `extracted_industry` partly holds section headings such as 'Warrant Investments- United States'). Correction to the 2026-10-17 read: HPS does print industry, as section heading rows ('Oil, Gas and Coal', 'Travel and Leisure'), not on the row.

5 of 30 do not print an industry (coverage limit): all Blackstone Private Real Estate Credit & Income (headings are CMBS / RMBS / mezzanine loans; loans are named by property). On the whole pool that is 5 of 57 flagged fund-quarters; Carlyle (1) and Fortress (1) were not sampled.

## Rule 5 preferred_published_as_common

Text kinds (text_says_preferred, text_and_rate): 147 rows, 1,429M FV, 43 fund-quarters, 8 funds (AB Private Credit Investors 101, North Haven 12, Blue Owl Credit Income 9, Sixth Street Specialty Lending 9, Sixth Street Lending Partners 7, Ares 3, BCRED 3, Golub 3). 29 of 30 real: filer calls it preferred or preference and the build publishes common (AB venture rows under 'U.S. Preferred Stock', Sixth Street 'Convertible Preference Shares', Blue Owl 'Series A Preferred Stock', North Haven 'Preferred Equity', Ares McLaren 'Senior preference shares'). Unclear (1): AB 'Swyft Parent Holdings LP / LP Interests' listed under the filer's 'U.S. Preferred Stock' heading. Sample concentration: Elysium BidCo is 8 of the 30 rows (two funds).

Rate-only kind (rate_on_common): 399 rows, 4,432M FV. Not reviewed; dropped by the owner's 2026-10-18 ruling.

## Recommendations

| rule | recommendation | stated fix |
|---|---|---|
| 1 issuer_name_differs_from_page | **Switch on after a fix** | (a) Pass a row when its published name, normalised, is a printed name cell on another row of the same filing (clears the spelling-variant and misjoin cases). (b) Allow a trailing legal-suffix difference (LLC, Inc., Ltd.). (c) For fund-quarters whose rule-1 blind share is >= 0.9 (New Mountain family, Stepstone), do not raise page-basis flags; the few that leak through are the industry-cell false alarms. Then re-sample. Also publish the blind-spot table with the rule, so a clean result on a blind fund-quarter is read as untested. |
| 2 unit_count_differs_from_row_text | **Switch on after a fix** | (a) Remove the issuer name from the text before the labelled-count regex (rule 5 already does this). (b) When the printed row carries a figure equal to the published count, pass even if the member prints a different labelled count. The HPS units-scale question needs an owner or filer-profile ruling; until then mark HPS x1000 flags unclear rather than open. |
| 3 pik_printed_not_published | **Switch on after a fix** | Raise findings on basis 'page' only; route member and member_page_silent to a weaker lane (or drop); do not raise pik_value_rounding. On the sample that leaves 26 real of 26. |
| 4 industry_not_published | **Switch on after a fix** | Record a per-fund 'no industry printed' exemption with evidence (Blackstone Private Real Estate Credit) instead of a threshold change; every other sampled fund-quarter is a fillable gap. The 0.80 threshold is still the builder's proposal, not owner-set. |
| 5 preferred_published_as_common, text kinds | **Switch on as is** (text kinds only) | Drop rate_on_common per the owner ruling. Keep the filer-heading case (AB LP interests under 'U.S. Preferred Stock') visible as unclear. |

Not done: no rule code changed, no rerun of the rules after the proposed fixes (their effect is expected, not measured), no review of the rate_on_common kind, Carlyle and Fortress rule-4 fund-quarters not read.

## Re-measure on the fixed rules (2026-10-19, commit ddc0e92)

The builder applied the fixes above (D-207, ddc0e92). Same method, seed 20261019: 30 finding rows per rule (max 6 per fund), plus 10 rows each of the new weaker kinds `units_scale_unclear` and `pik_member_text_only` (reported apart), and 30 of the 59 rule-4 finding fund-quarters. Scripts: `scripts/v05_evidence/candidate_rules_falsealarm_sample_v2.py`, `..._score_v2.py`. Labels: `v05_rule_candidates_falsealarm_2026-10-19_labels.csv`, `..._2026-10-19_rule4_fq.csv`. The first-sample figures above are unchanged.

| rule | old precision (95% CI) | new real / false / unclear | new precision | 95% Wilson |
|---|---|---|---:|---|
| 1 issuer_name_differs_from_page | 0.69 (0.51-0.83) | 30 / 0 / 0 | 1.00 | 0.89-1.00 |
| 2 unit_count_differs_from_row_text, findings | 0.92 (0.76-0.98) | 30 / 0 / 0 | 1.00 | 0.89-1.00 |
| 3 pik_printed_not_published, findings | 0.90 (0.74-0.96) | 30 / 0 / 0 | 1.00 | 0.89-1.00 |
| 5 preferred_published_as_common, text | 1.00 (0.88-1.00) | 29 / 0 / 1 | 1.00 | 0.88-1.00 |
| 4 industry_not_published, fund-quarters | 0.83 printed | 30 printed / 0 not | 1.00 | 0.89-1.00 |
| weaker: units_scale_unclear | - | 3 / 3 / 4 | 0.50 | 0.19-0.81 |
| weaker: pik_member_text_only | - | 3 / 3 / 4 | 0.50 | 0.19-0.81 |

**Rule 1.** No false alarms. 2 of the 30 real rows are cosmetic ('Freddys' for "Freddy's", 'L V F Holdings' for 'LVF Holdings'); counting those as not real gives 28/30 (0.93). Real patterns: Apollo group prefix (6), instrument or industry appended, member typos ('Accordian', 'Martson', 'Reinsureance', 'GPZN', 'Parfums Holding'), section residue ('and Consumer Products Belk, Inc.'). Of the first sample's 9 false alarms, 7 no longer flag; Antares 'ClearCapital' (spacing_only) and 26North 'Ascend Partners' still do, so the published spelling printed on sibling rows is not yet passed. One first-sample real error was lost: MidCap equity in 'Wildcat Parent LP' published as 'Wildcat BuyerCo, Inc.' no longer flags, because the borrower name is printed on the loan rows and the "printed elsewhere in the filing" pass accepts it.

**Rule 2.** 30 of 30 findings real (sibling row's count 9, /1000 2, count from another quarter 2 (MidCap AIC 142 vs 534,375, both directions), labelled not published 1, proxy count printed nowhere 16). Both first-sample false alarms no longer flag.

**units_scale_unclear (10).** 4 HPS rows stay undecidable (274 / 2,000 / 3,528 under 'Par Amount/Units'). 3 Blue Owl rows are right as published: Blue Owl printed BEHP Co-Investor II as 1,269,969 units in 2023-03-31 and 1,270 in 2024-09-30, so its 2024 schedule is in thousands (BEHP 1,269,969, Hercules 10,000, Insight CP 989,000). 3 are real errors held in the weaker kind: 26North FH DMI 400,429,000 for 400,429 shares at cost 400k (labelled real in the first sample; now demoted), T Series Leaf Home 250,000 for 250 (the same table prints full counts such as 500,000 and 1,383,156), Golub Creek Parent 1,279,000 = cost x1000 (row prints 1 unit). Correctly kept out of findings; a row test cannot split these, a per-filer scale fact can.

**Rule 3.** 30 of 30 page findings real (PIK not published 24; pik_rate holds spread, floor or all-in 6). The first-sample rounding false alarm no longer flags; the two member-versus-page false alarms moved to pik_member_text_only.

**pik_member_text_only (10).** 3 real and printed on the visible page; the page reader did not join the row (Crescent BioAgilytix prints '(including 275 PIK)', 0.75 published; GS SPay '(incl. 3.50 % PIK)', 9.25 published; GS Gainsight 'S + 6.75 % PIK', none published). 3 false: member disagrees with the page (AB American Physician), member carries the next row's PIK (Antares Accelerate), stale member (Crescent Granicus 2023-12-31). 4 unclear: visible row prints no rate (Crescent Omni, Envocore, iLending, Lighthouse). Correctly kept out of findings.

**Rule 4.** All 30 sampled fund-quarters print an industry, including the newly flagged Lord Abbett (headings 'Commercial Services & Supplies', 'Pharmaceuticals') and Fortress ('IT Services', 'Ground Transportation'). The BREC exemption removed the only not-printed fund.

**Rule 5.** 29 of 30 real; unclear again AB 'Swyft Parent Holdings LP / LP Interests'. The AB 'Avant NewCo Holdings, L.P. / Class A Units' rows (2026-03-31, 2026-06-30) still flag: the visible page lists them under 'U.S. Preferred Stock - 1.01 %', while their neighbours print 'Series C Preferred' / 'Series B-1 Preferred' explicitly. In the pool, 100 of 147 rows carry 'preferred' only in the member's section heading, all AB: 83 venture 'Series X' rows (preferred in substance) and 17 that are not Series rows (Avant Class A Units, Bowline LLC Units, Content Square 'Ordinary Shares', Ntiva Class A, Rubrik Class B, SBS Class A, Swyft LP Interests, Knockout 'Perpetual'). Whether a heading alone is "the filer calls it preferred" is an owner ruling; Content Square 'Ordinary Shares' looks misfiled rather than preferred.

### Recommendation on the fixed rules

| rule | recommendation |
|---|---|
| 1 | **Switch on.** Follow-ups: pass the published spelling when it is printed on sibling rows (ClearCapital, Ascend Partners); restrict the "printed elsewhere" pass to the same position's or issuer block's rows so a member naming another group entity (Wildcat) still flags. Publish the blind-spot table with it. |
| 2 | **Switch on** (findings only). Keep units_scale_unclear out; resolve it with per-filer scale facts (Blue Owl 2024+ in thousands, published right; 26North and T Series not, published wrong; HPS to be ruled). |
| 3 | **Switch on** (page findings only). Keep pik_member_text_only out; its real cases are page-join misses, so fix the join rather than promote the kind. |
| 4 | **Switch on** at the 0.80 finding level with the BREC exemption. Warning level (0.90) not reviewed. |
| 5 | **Switch on** for 'preferred' on the instrument or printed row. Hold the 17 AB heading-only non-Series rows as unclear pending the owner's ruling. |

Same caveats: 30-row fund-capped samples; "real" is page versus published, not proof the rest is right. Not done: the rule-4 warning level, the other 29 rule-4 fund-quarters, a rerun after the follow-ups.
