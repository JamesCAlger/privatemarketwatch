# Reading backlog: real errors found by reading each fund against its filings

Started 2026-10-10 on the owner's instruction ("i want the same attention given to the largest
first batches than to the first 10. read against filings"). One report per fund is kept in
`docs/investigations/v05_readings/<cik>.md` (written by read-only readers under
`v05_readings/BRIEF.md`; each quotes printed lines, accessions and contexts). This file lists what
each reading found that is a real error, and its state. "Built" means a fund sandbox shows the
result; nothing here is published. False alarms and as-filed groups are in the reports and are not
yet turned into proposed dispositions.

State at the last edit: 40 funds read (batches 3 to 10, Lord Abbett, Overland); readers running on
the other 15 funds of batches 11 to 13; the ten parked small funds not read.

## Defects that repeat across funds

| Defect | Where | State |
|---|---|---|
| Reference rate guessed from the report date | above 60 pct of loan rows in 31 of 77 funds (`v05_readings/cohort_field_health.txt`) | Fixed by naming the printed column where the header is known: Barings, Blue Owl Technology, T. Rowe Price OHA, Carlyle, Goldman Sachs BDC, Stone Point, HPS Corporate Capital Solutions, T Series, both New Mountain funds, Nuveen Churchill, Ares Core, Blackstone Real Estate Credit (built; checked against the page for T. Rowe Price OHA and Carlyle only). Not started: Monroe, MSD, North Haven, Sixth Street Specialty Lending, both Antares funds, Crescent, Jefferies, and the per-row benchmark tag (2025 on) that nothing reads |
| Issuer name is the whole label or carries a row number, tranche words or the industry | every quarter in 11 funds, most quarters in 8 more | Built: Barings, BCRED, HPS, North Haven, Monroe, T Series, HPS Corporate Capital Solutions, both Fidelity funds. Tested regex in the report, not applied: Stone Point, T. Rowe Price OHA, Diameter, Carlyle, Bain, Golub BDC 4, New Mountain Guardian IV, Nuveen Churchill, Sixth Street Specialty Lending, Crescent, Blue Owl Technology, MSD, Lord Abbett, Ares Core |
| Coupon, cash margin and PIK margin tagged apart | both BlackRock funds, TPG Twin Brook | Built `f1a` (`rate_tag_reading`): BlackRock IQN 9.45 as printed (was 5.76) |
| Loans with a PIK tag and no published rate | most funds | `filed_rate_reading` / `pik_only_tag_reading` set where the page shows the reading; the spread-plus-PIK case waits for the owner (D-092) |
| Rows of another note published as positions | Barings, T Series, HPS Corporate Capital Solutions, New Mountain (both), Jefferies, both Antares funds, KKR (both), Twin Brook | Built for all but Twin Brook (`schedule_row_tags`, `unfunded_rows`, two rules) |
| Facts filed on a prior date's context | Carlyle, Crescent, Bain (re-dated, built); Fidelity Fund 104.9M, Trinity, AB, Goldman Sachs BDC (a value on another date's context of the same member: no setting) | partly |
| Values filed without the thousands scale | Bain 33.5M, Stone Point 10.6M, Stepstone, VISTA (rules exist) | not started (needs a wrapper-switched rule) |
| Rows printed with a dash for fair value dropped (cost understated) | Goldman Sachs BDC up to 132.6M of cost, Trinity, Diameter, AB, MidCap, Crescent, Sixth Street Specialty Lending, Jefferies, Bain | not started (shared: keep a cost-only row at fair value 0) |
| Fund-level: net investment income holds total income or a per-share value; net assets missing or from the prior column | Goldman Sachs BDC, Goldman Sachs PMMC II, AB, Monroe, Blackstone Real Estate Credit, North Haven, Blue Owl Technology, New Mountain Guardian IV, Jefferies, MidCap, APS | not started |
| Promoted corrections and rules that are wrong or plugs | `column_remap` at 2025-12-31: Bain, Stepstone, Golub BDC 4, Crescent, Senior Credit pulled; Audax, Silver Capital, Twin Brook, AGL not read. Plug or pinned rules: Antares Strategic add rule, Bain SLP rule, North Haven and Monroe look-through rules, Trinity, Diameter | partly |
| Equity or securities classed as loans | T. Rowe Price OHA 66M, HPS Corporate Capital Solutions up to 145M, Stone Point 21M, T Series, Blackstone Real Estate Credit 248M of securities, Lord Abbett restored rows | not started (class from the page section) |

## By fund: totals against the filed investments figure after the fixes built so far

| Fund | Before | Now (sandbox) | What is left on totals |
|---|---|---|---|
| KKR FS Income Trust / Select | 13M to 571M / 2.5M to 316M over | 1.5M to 14M / 1.7M to 9.7M over in nine / five quarters (`k1b`) | unmatched commitments, not read |
| Barings | 203.4M over at 2023-06-30 | 6.9M under there, equal elsewhere (`b1a`) | two real rows (c-838, c-329) |
| Lord Abbett | 48M to 199M under | equal in all seven (`b2a`) | restored JV and equity rows class as loans |
| Overland | 91M to 215M under | Treasury bill published as cash-class (`b2a`) | owner: cash class or investment row; Summit 4.0M |
| Fidelity Private Credit Co | 9M to 67M off in five | equal but 2023-06-30, 1.4M under (`c1a`) | money market row |
| Fidelity Private Credit Fund | 13M to 208M under in nine | four quarters left (`d1a`) | 104.9M and 60.6M filing errors; two 2023 quarters |
| Carlyle | 62.5M under at 2024-12-31 | equal in all (`c2a`) | |
| Goldman Sachs BDC | off in twelve, up to 20M | 0.9M to 4.1M under in three (`d2a`) | untagged cells; cost short through dash rows |
| MidCap Financial | off in four | two quarters, 18.0M over and 12.9M under (`c2a`) | two rows the filing tags wrongly; 'Warrants' total |
| HPS Corporate Capital Solutions | 2M to 5M over in four | equal in all (`d1a`) | |
| T Series | 2M to 20M over in four | 1.7M under in one (`d1a`) | |
| Crescent Capital BDC | up to 30.8M under | 6.3M, 6.4M over, 1.2M under (`e1a`) | Ancora subtotal; MB2 Dental cell |
| Bain | 33.5M, 41.5M under | 33.5M, 11.2M under (`e1a`) | unscaled and whole-dollar rows |
| Jefferies | 0.5M to 1.6M under in seven | 1.2M over in one (`e1a`) | two subtotals |
| Antares Strategic | 2M to 9.5M under | 3.3M to 4.2M over in three (`e1a`) | plug add rule to retire |
| New Mountain Private Credit | 36.9M over at 2024-12-31 | equal in all (`f1a`) | |
| New Mountain Guardian IV | 2.0M over at 2024-12-31 | equal in all (`e1a`) | |
| Stone Point | 10.6M under at 2025-12-31 | unchanged | three unscaled rows |
| Stepstone | six quarters short | unchanged (`d1a`) | twins, misc; rates wrong in six quarters |
| Nuveen Churchill | 5M to 16M under in three | unchanged | as filed (figure includes cash) |
| BCRED, HPS, North Haven, Monroe, MSD, Blue Owl Technology, both BlackRock funds, Twin Brook, T. Rowe Price OHA, Diameter, Antares Private Credit, APS | equal | equal | (names, rates, classes per the reports) |

Per-fund detail beyond totals (rates, names, classes, fund-level figures, one-row filing errors) is
in each report; most of it is not yet fixed.

## 2026-10-11: one fund at a time, largest first (decisions D-099 to D-104)

Each fund built alone, every published field compared with its earlier sandbox, fixes read on the
page first. Nothing published, pushed or committed. "Proposed" = a reason written for the owner in
`data/overrides/finding_dispositions_proposed/fund_<cik>.json`; the ledger does not read it.

| Fund | Sandbox | Published vs filed | Outstanding | Proposed | Left open | Main changes |
|---|---|---|---|---|---|---|
| MSD 0001849894 | `m1a` | equal, 13 of 13 | 42 (was 58) | 38 | 4 | SONIA / SARON / BBSW / CDOR read from the page (65 rows, 2.7B); names 196 to 162; 17 row corrections (Accession loan tagged as Titan, 49.3M) |
| North Haven 0001851322 | `n1b` | equal, 13 of 13 | 31 | 23 | 8 | names split (69 loans, 778M at 2025-09-30) and ordinals stripped; preferred equity no longer loans (up to 39M a quarter); 659 reference rates; net assets 2023-09-30; hierarchy-note row removed |
| Monroe 0001742313 | `mo1c` | equal, 13 of 13 | 63 | 28 | 35 | names 3,536 to 578 with the instrument kept; 113 equity rows classed; 575 reference rates; PIK-only coupons (299 to 204 loans without a rate) |
| Blue Owl Technology 0001869453 | `o1b` | equal, 13 of 13 | 6 (was 35) | 5 | 1 | names 900 to 334; OEConnection loan (17.1M) and five other rows corrected; net assets of two 2023 quarters; LLC interests no longer loans |
| Barings 0001859919 | `ba1e` | equal, 13 of 13 (was 6.9M under in one) | 48 | 11 | 37 | two real rows restored; 300 reference rates (BBSY, BKBM, STIBOR ...); seven loans get rates from a sibling context |
| TPG Twin Brook 0001913724 | `tb1c` | equal in every quarter | 25 (was 36) | 15 | 10 | a harmful promoted correction pulled (SimiTree); verifier fixed for coupon-and-margin filers; 401 reference rates |
| Antares Strategic Credit 0001993402 | `as1d` | equal to the printed total, 8 of 9 (0.3M over in one) | 45 (was 70) | 32 | 13 | plugged money-market rule pulled, tagged row published as cash; 115 reference rates; two unnamed rows named; two share counts |
| Ares Core Infrastructure 0002031750 | `ac1b` | equal, 7 of 7 | 30 (was 32) | 19 | 11 | names 128 to 80 with the instrument kept; two unit counts corrected |

Next by size: Sixth
Street Specialty Lending 0001508655, Stepstone Private Credit 0001950803, then the D-082 list.

Defects found today that are not fixed (owner to hear):
- The cost proxy invents a cost from the first fair value of a position's chain; cleaner names
  chain more rows (Blue Owl Technology: 4,994,000 on an undrawn line worth -0.3M; 631 proxy rows
  in that fund).
- Year-end and per-share fund-level income errors (North Haven, Monroe, Blue Owl Technology):
  shared extractor.
- Rows printed 'x % Cash, y % PIK' publish no rate for a fund read as all-in (Barings, 13 quarters).
- Loans printed 'S + x % PIK' or with a PIK tag and a spread still wait on D-092 (Monroe 204 loans,
  Twin Brook 5 to 18 a quarter).
- GICS labels move when a name is cleaned (814 to 1,007 rows a fund); not checked against the
  printed industry heading.

Owner rulings applied the same day (D-106): no proxy cost where none is filed (all funds); a
cash-axis member naming a fair-value-hierarchy category is not cash and not a position.
Found the same day (D-108): industry labels are a name-keyed guess with a cache; cleaning names
empties the label in fund sandboxes (North Haven +516 rows without one, Monroe +659, Blue Owl
Technology +344, Ares Core +42).

## Run of 2026-10-12 night to 2026-10-13 (funds 19 to 62 by size, one at a time)

Each fund built alone in its own sandbox. 'Outstanding' is that sandbox's ledger; nothing was
published. Detail per fund is in the decision log entry named.

| Fund | Sandbox | Published v filed | Outstanding | Main change | Decision |
|---|---|---|---|---|---|
| Sixth Street Specialty Lending 0001508655 | `ss1c` | see log | 105 | names, class of three rows | D-110 |
| Stepstone Private Credit 0001950803 | `st1b` | short in 3 quarters (1.2M to 10.0M) | 48 | no-PIK reading | D-112 |
| KKR FS Income Trust 0001930679 | `kk1c` | over in 9 quarters (1.5M to 14.1M) | 90 | rate column, industry segment | D-113 |
| Goldman Sachs BDC 0001572694 | `gs1b` | equal, 13 of 13 | 92 | untagged and misdated values | D-114 |
| T. Rowe Price OHA 0001901612 | `tr1a` | equal | 13 | none | D-115 |
| MidCap Financial 0001578620 | `mc1c` | equal, 13 of 13 | 120 | rules, industry guards | D-116 |
| Stone Point Credit 0001825384 | `sp1a` | equal | 45 | none | D-117 |
| Diameter Credit 0001906381 | `di1b` | see log | 34 | settings | D-118 |
| Carlyle Secured Lending III 0001872371 | `ca1b` | see log | 30 | settings | D-119 |
| Fidelity Private Credit Fund 0001920453 | `fi1c`, `fd1a` | equal but two 2023 quarters | 38 | 13 untagged values; instrument text | D-120, D-130 |
| Trinity Capital 0001786108 | `tn1b` | small gaps in six quarters | 88 | two misdated loans | D-121 |
| Golub Capital BDC 4 0001901164 | `gb1b` | see log | 28 | names | D-122 |
| Nuveen Churchill PCAP 0001911066 | `nu1b` | short in three 2023 quarters (as filed) | 27 (was 35) | names no longer cut at the legal form | D-123 |
| BlackRock Private Credit 0001902649 | `bk1a` | equal | 22 | three headings | D-124 |
| HPS Corporate Capital Solutions 0001989817 | `hc1a` | equal | 12 | none | D-125 |
| T Series BDC 0001885968 | `ts1a` | 1.7M under in one quarter | 25 | none | D-125 |
| New Mountain Guardian IV 0001925531 | `ng1b` | equal | 21 | names 568 to 227 | D-125 |
| New Mountain Private Credit 0002037804 | `np1a` | equal | 41 | check-accepted entry | D-126 |
| Blackstone Private Real Estate Credit 0002049733 | `br1a` | equal | 1 | none | D-126 |
| AB Private Credit Investors 0001634452 | `ab1b` | see log | 66 | industry from the member (341 to 5,228 rows) | D-126 |
| KKR FS Income Trust Select 0001975736 | `ks1a` | over in five quarters (1.7M to 9.7M) | 43 | sister settings | D-126 |
| Bain Capital Private Credit 0001899017 | `bn1b` | equal (was 33.5M and 11.2M under) | 71 (was 80) | four unscaled rows; names 950 to 390 | D-127 |
| APS BDC 0002083477 | `ap1c` | equal | 2 | maturities and rates now read from the page | D-128 |
| Jefferies Credit Partners 0001959604 | `jf1b` | 1.2M over in one quarter | 11 | 'continued' headings | D-128 |
| Antares Private Credit 0001976336 | `an1b` | equal | 32 (was 47) | tagged money-market row replaces two add rules | D-128 |
| Fortress Private Lending 0002012139 | `fo1b` | equal | 13 (was 17) | rate column, foreign principal | D-129 |
| Fidelity Private Credit Company 0001899996 | `fc1b`, `fd1a` | 1.4M under in one quarter | 43 | instrument text | D-130 |
| VISTA Credit Strategic Lending 0001919369 | `vi1b` | equal | 19 | rate source, software headings | D-131 |
| 26North BDC 0001950976 | `tn2b` | equal | 17 | industry from the member (12 to 683 rows) | D-132 |
| Goldman Sachs PMMC II 0001772704 | `gp1b` | equal | 42 (was 54) | sister settings; SONIA and Canadian prime | D-133 |
| Crescent Capital BDC 0001633336 | `cc1c` | equal (was off in three quarters) | 51 (was 45) | subtotal removed, untagged value | D-134 |
| Apollo Origination II (Levered) 0002052152 | `ao1c` | equal | 20 | industry on every row | D-135 |
| Overland Advantage 0001965934 | `ov1c` | 'under' by the Treasury bill in five quarters | 44 | cut-off member named | D-136 |
| NMF SLF I 0001766037 | `nm1b` | off in four quarters (-6.1M to +16.4M) | 63 (was 65) | names 994 to 333 | D-137 |
| Lord Abbett Private Credit 0002008748 | `la1b` | equal | 21 | names 266 to 112 | D-138 |
| TCW Direct Lending VIII 0001825265 | `tw1a` | 1.1M under in one; no filed total in three | 76 | none | D-139 |
| AGL Private Credit Income 0002011498 | `ag1c` | equal | 19 | instrument text, industry | D-140 |
| MidCap Apollo Institutional 0002006758 | `ma1a` | equal | 26 | Apollo settings | D-141 |
| Apollo Origination II (unlevered) 0002052153 | `au1a` | equal | 40 | Apollo settings | D-141 |
| Silver Point Specialty Lending 0001646614 | `sv1b` | see log | 123 | country headings no longer an industry | D-142 |
| TCW Direct Lending VII 0001715933 | `t71a` | no filed total in eight quarters | 143 | none | D-142 |
| Phillip Street Middle Market Lending 0001948368 | `ps1b` | equal | 35 (was 41) | foreign principal, rate column | D-143 |
| Crescent Private Credit Income 0001954360 | `cp1b` | 1.5M and 2.3M under in two quarters | 61 (was 67) | footer no longer an industry; foreign principal | D-143 |
| Varagon Capital 0001784700 | `va1a` | 0.7M to 6.4M under in five quarters | 64 | none | D-143 |

Not reached in this run: the ten parked small funds (D-078, D-079) and Commonwealth 0001841514,
Senior Credit Investments 0001959568, TCW Direct Lending 0001603480, Silver Capital 0001674760,
Manulife 0001988280.
| 2026-10-15 | 0002031750 Ares Core Infrastructure Fund | acxb | INCOMPLETE | 38 findings, 36 outstanding, 35 proposed, 1 parked (shared income step) | D-168 |
| 2026-10-15 | 0001508655 Sixth Street Specialty Lending | ssxf | INCOMPLETE | 117 findings, 59 outstanding, 56 proposed, 3 parked | D-169 |
| 2026-10-15 | 0001950803 Stepstone Private Credit Fund | spxf | INCOMPLETE | 65 findings, 42 outstanding, 40 proposed, 2 parked; 2 declared total exceptions | D-170 |
| 2026-10-15 | 0001930679 KKR FS Income Trust | kfxh | PASS | 47 findings, 39 outstanding, 39 proposed | D-171 |
| 2026-10-15 | 0001572694 Goldman Sachs BDC | gsxf | NEEDS_ORCHESTRATOR (request declined) | 154 findings, 88 outstanding, 88 proposed | D-172 |
| 2026-10-15 | 0001901164 T. Rowe Price OHA Select | trxd | PASS | 41 findings, 6 outstanding, 6 proposed | D-173 |
| 2026-10-15 | 0001278752 MidCap Financial Investment Corp | mfxi | PASS | 145 findings, 84 outstanding, 84 proposed | D-174 |
