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
