"""Append the v0.5 row corrections of decisions D-021 and D-032 to data/overrides/row_corrections.csv.

Each spec names one published row (fund, quarter, a phrase that must match exactly one identifier in the sandbox)
and the fields to set, with the printed-schedule evidence. Keys (accession, exact identifier) are read from the
sandbox so they match what the build sees. Rows already present are skipped. Nothing is written without --write.

    python scripts/v05_evidence/make_row_corrections.py <label> [--write]
"""
import csv
import io
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label = sys.argv[1]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
BCRED, OWL, HPS, APOLLO, ARES = "0001803498", "0001812554", "0001838126", "0001837532", "0001287750"
ASIF, GS, SIXTH, OAKTREE = "0001918712", "0001920145", "0001925309", "0001872371"
TCWSTAR = "0001916608"
COUPON_AS_SPREAD = "Spread fact holds the coupon and there is no rate fact; the printed line reads "
PSC = ("Printed: 'First lien senior secured loan 11.53 % SOFR (Q) 6.00 % 07/2019 07/2025 34.2' then 11.29 / 5.75 (0.2), "
       "11.41 / 6.00 (11.3), 11.53 / 6.00 (2.4), 11.54 / 6.00 (6.6); ")
PREFERRED = {"asset_category": "EQUITY_PREFERRED", "index_classification": "PREFERRED_EQUITY"}
LOAN = {"asset_category": "LOAN", "index_classification": "DIRECT_LENDING", "asset_class": "PRIVATE_CREDIT"}
OPERATING_EQUITY = {"issuer_category": "CORPORATE", "index_classification": "COMMON_EQUITY", "exposure_type": "DIRECT",
                    "asset_class": "PRIVATE_EQUITY"}
KASEYA = ("Spread fact tagged 0.025, the PIK part; the printed line reads 'SR + 6.25 % ( 2.50 % PIK)' "
          "(10-Q 2023-06-30: delayed draw '06/2024 265 225 265', revolver '06/2029 1,085 1,011 1,075')")
AMERGIN = ("Printed under Equity Investments as 'Amergin Asset Management, LLC | Class A Units | 50,000,000 | cost 1'; an operating "
           "company stake, classed as a credit fund interest because the name contains 'Asset Management'")
NO_RATE_FACT = "No rate or spread fact on the row's context; the printed line reads "
WRONG_MEMBER = ("The filer's member names a loan, but its context carries the units, cost and value of an equity line of the "
                "same issuer; the printed line reads ")
EQUITY = {"asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "asset_class": "PRIVATE_EQUITY"}
SPECS = [
    (APOLLO, "2024-06-30", "Paymentsense", {"interest_rate": "12.5"},
     "Rate fact tagged 0.00125; the row text reads 'Interest Rate 12.50% (includes 6.25% PIK)'"),
    (APOLLO, "2024-09-30", "Paymentsense", {"interest_rate": "12.5"},
     "Rate fact tagged 0.00125; the row text reads 'Interest Rate 12.50% (includes 6.25% PIK)'"),
    (APOLLO, "2025-12-31", "GENMAB FINANCE LLC Investment Type First Lien Secured Debt - First Lien Secured Debt - Corporate Bond",
     {"interest_rate": "6.25"}, "No rate fact; the row text and printed line read 'Corporate Bond 6.25 %'"),
    (APOLLO, "2026-03-31", "Rocket Youth Brands Holdco LLC Investment Type First Lien Secured Debt - Delayed Draw",
     {"fair_value": "1884000"},
     "Fair value fact tagged -1884000; printed line reads 'Delayed Draw ... 2,047 2,013 1,884' and the issuer subtotal 11,000 "
     "equals 9,140 + 1,884 - 24"),
    (APOLLO, "2026-03-31", "SAVATREE CI Investment Type First Lien Secured Debt – Delayed Draw", {"fair_value": "-248000"},
     "Fair value fact tagged 248000; printed line reads 'Delayed Draw ... - ( 44 ) ( 248 )' and the issuer subtotal 16,538 "
     "equals 16,653 - 248 + 133"),
    (BCRED, "2022-12-31", "Huntington Bancshares Inc", LOAN,
     "Printed in the JV schedule's Bonds section: 'Huntington Bancshares Inc | 4.44 % | 8/4/2028 | 620 | 598 | 592'; a debt security"),
    (BCRED, "2023-09-30", "GTCR Investors LP - A-1 Units, Verdelite JV LP", LOAN,
     "Printed under First Lien Debt: 'GTCR Investors LP - A-1 Units | SOFR + 3.00 % | 8.40 % | 9/20/2030 | 3,335 | 3,319 | 3,336'"),
    (HPS, "2025-12-31", "OneTeam Partners, LLC - Class D Units", PREFERRED,
     "Printed as 'OneTeam Partners, LLC - Preferred Units | 8.00 % | 8.00 %'"),
    (HPS, "2026-03-31", "OneTeam Partners, LLC - Class D Units", PREFERRED,
     "Printed as 'OneTeam Partners, LLC - Preferred Units | 8.00 % | 8.00 % | 177,651 | 947 | 1,241'"),
    (OWL, "2024-09-30", "Amergin Asset Management, LLC", OPERATING_EQUITY, AMERGIN),
    (OWL, "2025-03-31", "Amergin Asset Management, LLC", OPERATING_EQUITY, AMERGIN),
    (OWL, "2025-12-31", "Amergin Asset Management, LLC", OPERATING_EQUITY, AMERGIN),
    (OWL, "2026-03-31", "Amergin Asset Management, LLC", OPERATING_EQUITY, AMERGIN),
    # decision D-032: the filer tagged the PIK part of the margin as the spread
    (OWL, "2023-06-30", "Kaseya Inc., First lien senior secured delayed draw term loan", {"basis_spread": "6.25"}, KASEYA, "D-032"),
    (OWL, "2023-06-30", "Kaseya Inc., First lien senior secured revolving loan", {"basis_spread": "6.25"}, KASEYA, "D-032"),
    (OWL, "2023-09-30", "Kaseya Inc., First lien senior secured delayed draw term loan", {"basis_spread": "6.25"}, KASEYA, "D-032"),
    (OWL, "2023-09-30", "Kaseya Inc., First lien senior secured revolving loan", {"basis_spread": "6.25"}, KASEYA, "D-032"),
    (OWL, "2023-12-31", "Kaseya Inc., First lien senior secured delayed draw term loan", {"basis_spread": "6.25"}, KASEYA, "D-032"),
    (OWL, "2024-06-30", "CivicPlus, LLC, First lien senior secured delayed draw term loan", {"basis_spread": "5.75"},
     "Spread fact tagged 0.025, the PIK part; the printed line reads 'First lien senior secured delayed draw term loan SR + 5.75 % "
     "( 2.50 % PIK) 08/2027 4,590 4,563 4,590'", "D-032"),
    # decision D-040: Ares tagged the coupon as the spread and filed no rate (10-Qs 2025-03-31 and 2025-06-30)
    (ARES, "2025-03-31", "LBC Breeze Holdings LLC, First lien senior secured loan 1", {"interest_rate": "12.4", "basis_spread": "8"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.40 % ( 7.00 % PIK) SOFR (Q) 8.00 % 12/2021 12/2027 3.3 3.3 3.1'", "D-040"),
    (ARES, "2025-03-31", "LBC Breeze Holdings LLC, First lien senior secured loan 2", {"interest_rate": "12.65", "basis_spread": "8.25"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.65 % ( 7.25 % PIK) SOFR (Q) 8.25 % 03/2023 12/2027 6.6 6.6 6.2'", "D-040"),
    (ARES, "2025-03-31", "Equinox Holdings, Inc., First lien senior secured loan", {"interest_rate": "12.55", "basis_spread": "8.25"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.55 % ( 4.13 % PIK) SOFR (Q) 8.25% 03/2024 03/2029 44.7 43.9 44.7'", "D-040"),
    (ARES, "2025-03-31", "SQ ABS Issuer, LLC, First lien senior secured loan", {"interest_rate": "13.92", "basis_spread": "9.5"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 13.92 % ( 3.00 % PIK) SOFR (M) 9.50 % 10/2024 09/2027 9.3 8.7 9.3'", "D-040"),
    (ARES, "2025-06-30", "LBC Breeze Holdings LLC, First lien senior secured loan 1", {"interest_rate": "12.38", "basis_spread": "8"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.38 % ( 7.00 % PIK) SOFR (Q) 8.00 % 12/2021 12/2027 3.4 3.4 3.2'", "D-040"),
    (ARES, "2025-06-30", "LBC Breeze Holdings LLC, First lien senior secured loan 2", {"interest_rate": "12.66", "basis_spread": "8.25"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.66 % ( 7.25 % PIK) SOFR (Q) 8.25 % 03/2023 12/2027 6.7 6.7 6.4'", "D-040"),
    (ARES, "2025-06-30", "Equinox Holdings, Inc., First lien senior secured loan", {"interest_rate": "12.55", "basis_spread": "8.25"},
     COUPON_AS_SPREAD + "'First lien senior secured loan 12.55 % ( 4.13 % PIK) SOFR (Q) 8.25% 03/2024 03/2029 45.2 44.4 45.2'", "D-040"),
    # decision D-040: Ares 10-K 2023-12-31, PSC Group: the rate and spread facts sit one loan down from their printed rows
    (ARES, "2023-12-31", "PSC Group LLC, First lien senior secured loan 2", {"interest_rate": "11.29", "basis_spread": "5.75"},
     PSC + "this row is '11.29 % SOFR (Q) 5.75 % 12/2021 07/2025 0.2 0.2 0.2' and carries no rate fact", "D-040"),
    (ARES, "2023-12-31", "PSC Group LLC, First lien senior secured loan 3", {"interest_rate": "11.41", "basis_spread": "6"},
     PSC + "this row is '11.41 % SOFR (Q) 6.00 % 12/2021 07/2025 11.3 11.3 11.3' and carries 11.29 and 5.75", "D-040"),
    (ARES, "2023-12-31", "PSC Group LLC, First lien senior secured loan 4", {"interest_rate": "11.53"},
     PSC + "this row is '11.53 % SOFR (Q) 6.00 % 04/2022 07/2025 2.4 2.4 2.4' and carries 11.41", "D-040"),
    (ARES, "2023-12-31", "PSC Group LLC, First lien senior secured loan 5", {"interest_rate": "11.54", "basis_spread": "6"},
     PSC + "this row is '11.54 % SOFR (Q) 6.00 % 12/2023 07/2025 6.6 6.6 6.6' and carries no rate fact", "D-040"),
    # decision D-040: Apollo 10-Q 2024-06-30, the margin is printed in pieces and the first piece was tagged
    (APOLLO, "2024-06-30", "Curia Global, Inc. Investment Type First Lien Secured Debt - Term Loan", {"basis_spread": "3.85"},
     "Spread fact tagged 0.0038; the printed line reads 'First Lien Secured Debt - Term Loan S+ 38 5, 0.75 % Floor 8/30/2026 "
     "27,269 26,063 25,755' and the row's own label reads 'Interest Rate S+385, 0.75% Floor'", "D-040"),
    (APOLLO, "2026-03-31", "OMH-Healthedge Holdings, Inc. Investment Type First Lien Secured Debt - Term Loan", {"basis_spread": "4.5"},
     "Spread fact tagged 0.005; the row's own label in the 10-Q reads 'First Lien Secured Debt - Term Loan Interest Rate S+450, "
     "1.00% Floor Maturity Date 4/1/2030' and the page reader reads a margin of 4.50 from the printed cell", "D-040"),
    # decision D-043: the first out-of-sample quarter. The same rows as in earlier quarters, read again on the 10-Q for 2026-06-30.
    (OWL, "2026-06-30", "Amergin Asset Management, LLC", OPERATING_EQUITY,
     "10-Q 2026-06-30, under Equity Investments: 'Amergin Asset Management, LLC | Specialty finance equity investment | N/A | N/A | "
     "50,000,000 | $ 1 | $ 2,061'; an operating company stake, classed as a credit fund interest because the name contains "
     "'Asset Management'", "D-043"),
    (HPS, "2026-06-30", "OneTeam Partners, LLC - Class D Units", PREFERRED,
     "10-Q 2026-06-30 prints 'OneTeam Partners, LLC - Preferred Units | 8.00 % | 8.00 % | 177,651 | 947 | 1,262'", "D-043"),
    (OWL, "2026-06-30", "KWOR Intermediate I, Inc. (dba Alacrity Solutions) | First lien senior secured loan", {"cost": "6675000"},
     "Cost fact carries a EUR unit and was not published; the 10-Q 2026-06-30 prints the row in dollars: 'First lien senior secured "
     "loan S+ 8.00 % 2/2030 6,721 - 6,675 6,402' (par, cost, fair value)", "D-043"),
    # decision D-049: Ares rows accepted "as filed" under X02, read on the printed page (scripts/v05_evidence/x02_page_read.py)
    (ARES, "2024-12-31", "HPCC Parent, Inc. and Patriot Container Corp, First lien senior secured loan",
     {"interest_rate": "13", "pik_rate": "7"},
     NO_RATE_FACT + "'First lien senior secured loan 13.00 % ( 7.00 % PIK) 09/2024 09/2030 78.4 78.4 76.2'", "D-049"),
    (ARES, "2022-09-30", "Xanadu Holdings 2019-1, LLC, Senior subordinated loan",
     {"interest_rate": "10.43", "pik_rate": "2.77", "basis_spread": "6.75"},
     NO_RATE_FACT + "'Senior subordinated loan 10.43 % ( 2.77 % PIK) LIBOR (Q) 6.75 % 6/2019 7/2030 71.3 71.3 67.1'", "D-049"),
    # decision D-053 (owner, 2026-10-08): Blue Owl Aptive prints the whole coupon; the rate tag is published as the rate
    (OWL, "2023-03-31", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 $ 8,689 $ 7,402 $ 8,037': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2023-06-30", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 $ 8,821 $ 7,630 $ 8,314': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2023-09-30", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 $ 8,955 $ 7,865 $ 9,179': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2023-12-31", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 9,091 $ 8,102 $ 9,318': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2024-03-31", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 9,228 $ 8,348 $ 9,482': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2024-06-30", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 9,368 $ 8,598 $ 9,532': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    (OWL, "2024-09-30", "Aptive Environmental, LLC, First lien senior secured loan", {"interest_rate": "12"},
     "Rate fact 0.12 and PIK fact 0.06; the printed line reads 'First lien senior secured loan 12.00 % ( 6.00 % PIK) 01/2026 9,515 $ 8,859 $ 9,801': "
     "12.00 is the whole coupon, of which 6.00 is paid in kind", "D-053"),
    # decision D-053 (owner, 2026-10-08): Ares 10-Q 2025-09-30, UP Intermediate: the members are one line out. The page prints
    # 'First lien senior secured revolving loan 03/2024 03/2031 - - -', 'First lien senior secured loan 8.75 % SOFR (Q) 4.75 %
    # 07/2025 03/2032 15.2 15.2 15.2' and 'Senior preferred units 15.00 % PIK 07/2025 10,340 1.1 1.1'.
    (ARES, "2025-09-30", "UP Intermediate II LLC and UPBW Blocker LLC, First lien senior secured revolving loan",
     {"interest_rate": "", "basis_spread": "", "reference_rate_type": "", "reference_rate_source": "", "coupon_type": ""},
     "Rate 8.75 and spread 4.75 are tagged on the revolver, which the page prints with no rate: 'First lien senior secured "
     "revolving loan 03/2024 03/2031 - - -'; they are the term loan's", "D-053"),
    (ARES, "2025-09-30", "UP Intermediate II LLC and UPBW Blocker LLC, First lien senior secured loan",
     {"interest_rate": "8.75", "basis_spread": "4.75", "pik_rate": ""},
     "A PIK rate of 0.15 is tagged on the term loan; the page prints 'First lien senior secured loan 8.75 % SOFR (Q) 4.75 % "
     "07/2025 03/2032 15.2 15.2 15.2' and the 15.00 % PIK on the preferred units below it", "D-053"),
    (ARES, "2025-09-30", "UP Intermediate II LLC and UPBW Blocker LLC, Senior preferred units",
     {"interest_rate": "15", "pik_rate": "15"},
     "No rate fact on the preferred units; the page prints 'Senior preferred units 15.00 % PIK 07/2025 10,340 1.1 1.1'", "D-053"),
    # Not correctable here: Rawlings loan 2 and Infinity Home Services loan 3 at 2025-03-31 and 2025-06-30 print a rate
    # ("9.20 % SOFR (Q) 4.75 %", "9.80 % SOFR (Q) 5.50 %", "8.66 % CORRA (M) 6.00 %") but are among the eight positions
    # restored from the issuer-name axis (D-018), which are built after row corrections are applied.
    (ARES, "2025-09-30", "The Hiller Companies, LLC, First lien senior secured loan 2", {"interest_rate": "9.05", "basis_spread": "4.75"},
     NO_RATE_FACT + "'First lien senior secured loan 9.05 % SOFR (Q) 4.75 % 07/2025 06/2030 2.1 2.1 2.1'", "D-049"),
    (ARES, "2025-09-30", "Imaging Business Machines, L.L.C. and Scanner Holdings Corporation, Senior subordinated loan",
     {"interest_rate": "14", "pik_rate": "7"},
     "The only rate fact is a PIK rate of 0.14, which is the whole coupon; the printed line reads 'Senior subordinated loan "
     "14.00 % ( 7.00 % PIK) 01/2017 12/2028 19.5 19.3 19.4'", "D-049"),
    (ARES, "2025-09-30", "Implus Footcare, LLC, First lien senior secured loan 3", {**EQUITY, "instrument_description": "Common units"},
     WRONG_MEMBER + "'Common units 07/2025 28,049,368 41.9 42.1'", "D-049"),
    (ARES, "2025-09-30", "Bragg Live Food Products, LLC and SPC Investment Co., L.P., First lien senior secured loan",
     {**EQUITY, "instrument_description": "Common units"}, WRONG_MEMBER + "'Common units 03/2019 14,850 8.4 22.3'", "D-049"),
    (ARES, "2025-09-30", "ID.me, Inc., First lien senior secured loan",
     {"asset_category": "EQUITY_PREFERRED", "index_classification": "PREFERRED_EQUITY", "asset_class": "PRIVATE_EQUITY",
      "instrument_description": "Series E preferred units"},
     WRONG_MEMBER + "'Series E preferred units 08/2025 10,827,926 16.0 16.0'; the member 'First lien senior secured revolving loan' "
     "carries the loan ('10.25 % ( 5.25 % PIK) 01/2025 01/2031 120.0 111.5 110.2')", "D-049"),
    (ARES, "2025-12-31", "MDCP Co-Investors (Jade I), L.P., First lien senior secured loan",
     {**EQUITY, "instrument_description": "Limited partnership interest"},
     WRONG_MEMBER + "'Limited partnership interest 06/2025 17,510,000 24.1 26.3'", "D-049"),
    (ARES, "2026-03-31", "APG Intermediate Holdings Corporation and APG Holdings, LLC, First lien senior secured loan",
     {**EQUITY, "instrument_description": "Class A membership units"},
     WRONG_MEMBER + "'Class A membership units 01/2020 9,750,000 9.8 6.3'", "D-049"),
    # decision D-074 (2026-10-09): rows of the next five funds read on the page
    (GS, "2025-06-30", "Berkeley Research Group LLC Industry Professional Services Interest Rate 7.55%", {"cost": "8540000"},
     "Cost tag reads 854; the printed line reads '7.55 % S + 3.25 % 05/01/32 8,600 8,54 0 8,624' (a stray space inside 8,540)", "D-074"),
    (GS, "2025-09-30", "123Dentist Inc. Industry HealthCare Providers & Services Reference Rate and Spread C+ 5.00% Maturity 08/08/29",
     {"maturity_date": "2029-08-08"},
     "The member reads 'Maturity 08/08/29'; the page prints '08/08/2 9' with a stray space and the page reading took 2002", "D-074"),
    (SIXTH, "2023-12-31", "ASP Unifrax Holdings, Inc. First-lien loan ($1,130 par", {"principal_amount": "1130000", "principal_amount_usd": "1130000"},
     "Principal tag is negative; the printed line reads 'First-lien loan ($ 1,130 par, due 12/2025 ) (3) 8/25/2023 SOFR + 3.90 % 9.25 % 1,055 1,051'", "D-074"),
    (SIXTH, "2024-09-30", "ASP Unifrax Holdings, Inc. First-lien loan ($1,993 par", {"principal_amount": "1993000", "principal_amount_usd": "1993000"},
     "Principal tag is negative; the printed line reads 'Second-lien note ($ 1,993 par, due 9/2029 ) 8/31/2023 7.10 % 7.10 % (incl. 1.25 % PIK) 1,488 1,355'", "D-074"),
    (SIXTH, "2024-12-31", "Flight Intermediate HoldCo, Inc. First-lien loan ($46,500 par",
     {"reference_rate_type": "", "reference_rate_source": "", "coupon_type": "Fixed"},
     "The member reads 'SOFR + 11.50%'; the page prints a fixed rate: 'First-lien loan ($ 46,500 par, due 4/2030 ) 10/3/2024 11.50 % 11.50 % 45,164 45,221'", "D-074"),
    (SIXTH, "2025-06-30", "X Holdings. Inc. First-lien loan (29,710 par",
     {"reference_rate_type": "", "reference_rate_source": "", "coupon_type": "Fixed"},
     "The member reads 'SOFR + 9.50%'; the page prints a fixed rate: 'First-lien loan ($ 29,710 par, due 10/2029 ) 5/6/2025 9.50 % 9.50 % 28,975 28,865'", "D-074"),
    (SIXTH, "2024-12-31", "Price Fx Inc. First-lien loan (EUR 910 par, due 10/2024)", {"maturity_date": "2029-10-31"},
     "The member reads 'due 10/2024'; the page prints 'First-lien loan (EUR 910 par, due 10/2029 ) 12/19/2024 E + 6.25 % 9.12 % 921 919'", "D-074"),
    (OAKTREE, "2023-09-30", "Impel Pharmaceuticals Inc., First Lien Term Loan 1", {"interest_rate": "16.06", "basis_spread": "10.75"},
     NO_RATE_FACT + "'First Lien Term Loan SOFR+ 10.75 % 16.06 % 3/17/2027 9,679 9,613 8,904'", "D-074"),
    (ASIF, "2025-03-31", "WRE Sports Investments LLC, First lien senior secured loan",
     {"basis_spread": "", "pik_rate": "5.5", "reference_rate_type": "", "reference_rate_source": "", "coupon_type": "Fixed"},
     "In this one filing the 5.50 % PIK part is tagged as a spread; the printed line reads 'First lien senior secured loan "
     "11.00 % ( 5.50 % PIK) 07/2031 35,206.6 34,454.6 35,206.6', and every other quarter tags it as PIK", "D-074"),
    (ASIF, "2025-12-31", "Steward Partners Global Advisory, LLC and Steward Partners Investment Advisory, LLC, First lien senior secured loan",
     {**EQUITY, "instrument_description": "Warrant to purchase Class W units", "shares_held": "138674"},
     WRONG_MEMBER + "'Warrant to purchase Class W units 12/2025 12/2032 138,674 2,644.6 2,644.6'", "D-074"),
    (ASIF, "2026-03-31", "Steward Partners Global Advisory, LLC and Steward Partners Investment Advisory, LLC, First lien senior secured loan",
     {**EQUITY, "instrument_description": "Warrant to purchase common stock", "shares_held": "138674"},
     WRONG_MEMBER + "'Warrant to purchase common stock 12/2025 12/2032 138,674 2,644.6 2,727.3'", "D-074"),
    (SIXTH, "2023-03-31", "BTRS Holdings, Inc, LLC First-lien loan ($1,988 par", {"basis_spread": "7.25"},
     "The member reads 'SOFR + 8.0'; the page prints 'First-lien revolving loan ($ 1,988 par, due 12/2028 ) 12/16/2022 "
     "SOFR + 7.25 % 12.06 % 1,575 1,663' (8.00 is the term loan's margin on the row above)", "D-077"),
    (SIXTH, "2023-03-31", "Disco Parent, Inc First-lien loan ($57,756 par", {"basis_spread": "7.5"},
     "The member reads 'SOFR + 6.75%'; the page prints 'First-lien loan ($ 57,756 par, due 3/2029 ) 3/30/2023 SOFR + 7.50 % "
     "12.39 % 56,169 56,326', and every later quarter's member reads 7.50", "D-077"),
    (ASIF, "2026-06-30", "AX VI VET Holding I ApS | First lien senior secured loan 5", {"interest_rate": "9.15", "pik_rate": "2.45"},
     "The rate and PIK tags are swapped (rate 0.0245, PIK 0.0915); the page prints 'First lien senior secured loan 9.15 % "
     "( 2.45 % PIK) NIBOR (S) 4.50 % 01/2029 304.2 299.8 33.5', and the prior quarter tags 9.15 and 2.45", "D-077"),
    (TCWSTAR, "2025-06-30", "Superior Industries International, Inc, Acquisition Date - 06/04/25",
     {"fair_value": "72532", "cost": "72532", "principal_amount": "72532", "principal_amount_usd": "72532"},
     "The three value tags carry scale 3 (thousands) on a schedule printed in dollars, giving 72,532,000; the page prints "
     "'Delayed Draw Term Loan - 12.32 % inc PIK ( SOFR + 8.00 %, 3.50 % Floor, all PIK) 0.0 % 72,532 06/04/26 72,532 72,532' "
     "beside the same issuer's term loan at 3,591,534 par, and 'Total Debt Investments 98.6 % 201,294,980 196,275,290'", "D-079"),
] + [
    (ASIF, quarter, phrase, {"reference_rate_type": "", "reference_rate_source": ""},
     "The member's label carries a loan's rate terms ('%s'); the page prints the row with no rate or reference rate: %s"
     % (terms, printed), "D-077")
    for quarter in ("2025-03-31", "2025-06-30")
    for phrase, terms, printed in (
        ("United Digestive MSO Parent, LLC and Koln Co-Invest Unblocked, LP, Class A interests", "0.1005, SOFR (Q), 0.0575",
         "'Class A interests 03/2023 100 100.0 139.8' (10-Q 2025-06-30)"),
        ("Bluejack Fire Acquisition, Inc. and Bluejack Fire Holdings LLC, Class A-1 units", "0.0905, SOFR (Q), 0.0475",
         "'Class A-1 units 01/2025 1,134 1,134.0 1,141.1' (10-Q 2025-06-30)"),
        ("Dorado Bidco, Inc., First lien senior secured revolving loan", "0.0632, SOFR (B), 0.02",
         "'First lien senior secured revolving loan 09/2031' with dashes for principal, cost and value (10-Q 2025-06-30)"))
]
# decision D-099: MSD Investment Corp., one-row filing errors read on the page (2026-10-11)
MSD = "0001849894"
MSD_NO_PIK = ("The whole rate is tagged with the paid-in-kind concept and there is no plain rate fact; the printed line "
              "carries no 'PIK': ")
MSD_SKY = ("No cost fact on the context; the published 5,000 is a proxy from the first fair value. The printed line shows "
           "a dash for par and for cost: 'Sky Merger Sub, LLC - Delayed Draw Term Loan ... 5/28/2029 -- -- ")
MSD_SKY_ID = "Sky Merger Sub, LLC - Delayed Draw Term Loan"
SPECS += [
    (MSD, "2024-12-31", "Titan Purchaser, Inc. Reference Rate and Spread S + 6.00% Interest Rate Floor 1.00% Interest Rate 9.34%",
     {"issuer_name": "Accession Risk Management",
      "instrument_description": "Delayed Draw Term Loan Reference Rate and Spread S + 4.75% Interest Rate Floor 0.75% "
                                "Interest Rate 9.34% Maturity Date 11/1/2029"},
     "The filer tagged this line on a second 'Titan Purchaser' member; the printed line reads 'Accession Risk Management - "
     "Delayed Draw Term Loan S + 4.75 % 0.75 % 9.34 % 11/1/2029 49,277 48,703 49,277 2.05' under Banking, Finance, "
     "Insurance & Real Estate, whose printed subtotal 308,744 includes it", "D-099"),
    (MSD, "2025-09-30", "Watchguard Technologies, Inc. Reference Rate and Spread S + 5.25%", {"pik_rate": ""},
     MSD_NO_PIK + "'S + 5.25 % 0.75 % 9.41 % 7/2/2029 74,147 72,308 73,962 2.67'", "D-099"),
    (MSD, "2025-09-30", "7Ridge Investments - Delayed Draw Term Loan", {"pik_rate": ""},
     MSD_NO_PIK + "'7Ridge Investments - Delayed Draw Term Loan (10)(11) S + 8.00 % 1.00 % 11.98 % 7/7/2028 -- 33 34 --'", "D-099"),
    (MSD, "2025-12-31", "Legends Hospitality Holding Company - Delayed Draw Term Loan", {"pik_rate": ""},
     MSD_NO_PIK + "'Delayed Draw Term Loan (6)(11) S + 5.00 % 0.75 % 8.73 % 8/22/2031 3,099 3,044 3,047 0.09'", "D-099"),
    (MSD, "2025-12-31", "Legends Hospitality Holding Company - Revolving Credit Facility", {"pik_rate": ""},
     MSD_NO_PIK + "'Revolving Credit Facility (6)(11) S + 5.00 % 0.75 % 8.73 % 8/22/2030 2,437 2,322 2,321 0.07'", "D-099"),
    (MSD, "2026-03-31", "Legends Hospitality Holding Company - Delayed Draw Term Loan", {"pik_rate": ""},
     MSD_NO_PIK + "'Delayed Draw Term Loan (6) S + 5.00 % 0.75 % 8.66 % 8/22/2031 3,727 3,669 3,669 0.11'", "D-099"),
    (MSD, "2026-03-31", "Legends Hospitality Holding Company - Revolving Credit Facility", {"pik_rate": ""},
     MSD_NO_PIK + "'Revolving Credit Facility (6)(11) S + 5.00 % 0.75 % 8.67 % 8/22/2030 3,938 3,828 3,827 0.12'", "D-099"),
    (MSD, "2024-06-30", "Beacon Mobility Corp. - Delayed Draw Term Loan", {"interest_rate": "13.94"},
     "Only the paid-in-kind concept is tagged (0.1394) and no plain rate; the printed line reads 'Beacon Mobility Corp. - "
     "Delayed Draw Term Loan (8)(9)(12) S + 8.60 % 0.00 % 13.94 % PIK 12/31/2025 1,285 1,263 1,266 0.08'", "D-099"),
    (MSD, "2024-06-30", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "5'", "D-099"),
    (MSD, "2024-09-30", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "21'", "D-099"),
    (MSD, "2024-12-31", "Sky Merger Sub, LLC Reference Rate and Spread S + 6.60% Interest Rate Floor 1.50% Interest Rate 10.91%",
     {"cost": "0"}, MSD_SKY + "37'", "D-099"),
    (MSD, "2025-03-31", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "52'", "D-099"),
    (MSD, "2025-06-30", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "68'", "D-099"),
    (MSD, "2025-09-30", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "84'", "D-099"),
    (MSD, "2025-12-31", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "99'", "D-099"),
    (MSD, "2026-03-31", MSD_SKY_ID, {"cost": "0"}, MSD_SKY + "115'", "D-099"),
    # fund-clearing loop, 2026-10-13: the count published for the warrant was the Class B preferred row's
    (MSD, "2024-09-30", "Metropolis Technologies Inc. - Warrant", {"shares_held": "4"},
     "The context's share-count fact is 4 (C_ef95e4b5, InvestmentOwnedBalanceShares) and the printed line reads 'Metropolis "
     "Technologies Inc. - Warrant (8)(9) 2/13/2034 4 189 215 0.01'; the published 6,314 is the count of the Class B preferred "
     "row above it, put there by the unit-scale normaliser (shares_held:pow10_shares), which compares rows of one issuer",
     "D-1849894-fundloop"),
]
# Phrases that are a whole identifier and also the start of another ('... secured loan' and '... secured loan 2').
EXACT = {"Impel Pharmaceuticals Inc., First Lien Term Loan 1",
         "Steward Partners Global Advisory, LLC and Steward Partners Investment Advisory, LLC, First lien senior secured loan",
         "UP Intermediate II LLC and UPBW Blocker LLC, First lien senior secured loan",
         "Aptive Environmental, LLC, First lien senior secured loan"}
con = duckdb.connect()
target = REPO / "data/overrides/row_corrections.csv"
data = target.read_bytes()
eol = "\r\n" if b"\r\n" in data else "\n"
existing = {(r["cik"].zfill(10), r["report_date"], r["accession_number"], r["bdc_investment_identifier"], r["field"])
            for r in csv.DictReader(io.StringIO(data.decode("utf-8")))}
buffer = io.StringIO()
writer = csv.writer(buffer, lineterminator=eol)
added = 0
# A sandbox holds some funds only: specs for a fund it does not hold are left alone, not failed.
held = {r[0] for r in con.execute(
    f"SELECT DISTINCT lpad(CAST(cik AS VARCHAR),10,'0') FROM read_parquet('{S}/private_markets_holdings.parquet')").fetchall()}
# decision D-101: Monroe Capital Income Plus, one row (2026-10-11)
MONROE = "0001742313"
SPECS.append((MONROE, "2025-12-31", "FLEET Response, LLC (fka RS Acquisition, LLC) 1 | Senior Secured Loans", {"interest_rate": ""},
              "Rate published 25.25 = a paid-in-cash tag of 15.28 plus the PIK tag 9.97; the page prints no cash rate, so the cash "
              "tag is withdrawn and the row reads like its two sibling rows (PIK 9.97, spread 6.10): 'FLEET Response, "
              "LLC (fka RS Acquisition, LLC) (21) SF 6.10 % 9.97 % PIK 12/13/2021 12/14/2026 11,577 11,521 8,671 0.3 %'", "D-101"))
# decision D-102: Blue Owl Technology Income Corp., one-row filing errors read on the page (2026-10-11)
OWLTECH = "0001869453"
OWLTECH_REALPAGE = ("No spread fact on the row's context (principal, cost and fair value only); the printed line reads "
                    "'RealPage, Inc.(8)(14) First lien senior secured loan S+ 3.00 % 4/2028 ")
SPECS += [
    (OWLTECH, "2025-12-31", "McQueen Bidco PTY LTD. (dba Infomedia) | First lien senior secured loan 1",
     {"issuer_name": "OECONNECTION LLC", "basis_spread": "4.5"},
     "The filer tagged this line on a second McQueen Bidco member (context c-416); the printed line reads 'OECONNECTION LLC(3)(4)(8) "
     "First lien senior secured loan S+ 4.50 % 12/2032 17,228 17,142 17,142'. McQueen's own line is 'S+ 4.50 % 12/2032 34,002 "
     "34,002 33,917'", "D-102"),
    (OWLTECH, "2025-03-31", "RealPage, Inc., First lien senior secured loan", {"basis_spread": "3"},
     OWLTECH_REALPAGE + "20,114 19,831 19,824'", "D-102"),
    (OWLTECH, "2025-06-30", "RealPage, Inc., First lien senior secured loan", {"basis_spread": "3"},
     OWLTECH_REALPAGE + "20,062 19,801 19,907'", "D-102"),
    (OWLTECH, "2023-09-30", "Engage Debtco Limited, First lien senior secured loan", {"basis_spread": "5.9", "pik_rate": "2.4"},
     "No spread or PIK fact on the row's context; the printed line reads 'Engage Debtco Limited(8)(21) First lien senior secured "
     "loan S + 5.90% (2.40% PIK) 7/2029 12,500 12,232 12,281 0.8 %'", "D-102"),
    (OWLTECH, "2024-09-30", "Blue Owl Credit SLF LLC, LLC Interest", {**EQUITY, "principal_amount": ""},
     "Printed under Equity Investments, Joint Ventures: 'Blue Owl Credit SLF LLC(21)(23)(26)(27)(28) LLC Interest N/A N/A N/A "
     "2,188 2,189 2,187 0.1 %'; the filer tagged the units as a principal amount and the row was classed a loan", "D-102"),
]
SPECS += [
    (OWLTECH, "2024-03-31", "Kaseya Inc., First lien senior secured loan", {"basis_spread": "6", "pik_rate": "2.5"},
     "Spread and PIK facts are swapped (spread 0.025, PIK 0.06); the printed line reads 'Kaseya Inc.(8) First lien senior secured "
     "loan S + 6.00 % ( 2.50 % PIK) 06/2029 67,903 66,830 67,903 3.1 %'", "D-102"),
    (OWLTECH, "2024-03-31", "Associations, Inc., First lien senior secured loan", {"basis_spread": "6.5", "pik_rate": "2.5"},
     "Spread and PIK facts are swapped (spread 0.025, PIK 0.065); the printed line reads 'Associations, Inc.(8) First lien senior "
     "secured loan S + 6.50 % ( 2.50 % PIK) 07/2027 21,120 20,938 21,120 1.0 %'", "D-102"),
    (OWLTECH, "2026-03-31", "Blue Owl Credit SLF LLC | LLC Interest", {"shares_held": "16161000"},
     "The units are tagged as a principal amount of 16,161,000; once the row is classed as equity the share count was filled with "
     "a proxy from an earlier quarter (14,293). Printed: 'Blue Owl Credit SLF LLC(3)(5)(24)(26)(30)(31) LLC Interest N/A N/A "
     "16,161 - 16,162 14,946'", "D-102"),
]
EXACT |= {"RealPage, Inc., First lien senior secured loan", "Engage Debtco Limited, First lien senior secured loan",
          "Blue Owl Credit SLF LLC, LLC Interest", "Kaseya Inc., First lien senior secured loan",
          "Associations, Inc., First lien senior secured loan", "Blue Owl Credit SLF LLC | LLC Interest"}
# decision D-103: Barings Private Credit Corp, 2023-06-30: three loans whose rate facts sit on a sibling context; the
# reference rate was guessed from the date. Run against a sandbox that holds the fund with D-103's wrapper settings.
BARINGS = "0001859919"
BARINGS_FINEXVET = ("Reference rate guessed from the report date (LIBOR); the printed lines read 'Finexvet Consumer Cyclical First Lien "
                    "Senior Secured Term Loan EURIBOR + 6.50 %, 9.8 % Cash 03/22 03/29 2,454 2,391 2,388 0.2 %' and 'First Lien "
                    "Senior Secured Term Loan EURIBOR + 6.50 %, 9.8 % Cash 05/23 03/29 5,500 5,304 5,278 0.4 %'")
SPECS += [
    (BARINGS, "2023-06-30", "Finexvet, Consumer Cyclical, First Lien Senior Secured Term Loan 1",
     {"reference_rate_type": "EURIBOR", "reference_rate_source": ""}, BARINGS_FINEXVET, "D-103"),
    (BARINGS, "2023-06-30", "Finexvet, Consumer Cyclical, First Lien Senior Secured Term Loan 2",
     {"reference_rate_type": "EURIBOR", "reference_rate_source": ""}, BARINGS_FINEXVET, "D-103"),
    (BARINGS, "2023-06-30", "Innovad Group II BV, Beverage, Food & Tobacco, First Lien Senior Secured Term Loan 2",
     {"reference_rate_type": "SARON", "reference_rate_source": ""},
     "Reference rate guessed from the report date (LIBOR); the printed line reads 'First Lien Senior Secured Term Loan SARON + "
     "6.50 %, 8.2 % Cash 05/23 04/28 162 161 156'", "D-103"),
]
# decision D-104: TPG Twin Brook, SimiTree Acquisition at 2025-12-31: the PIK margin is tagged 1.75 (not 0.0175), and the
# spread was then published as the PIK rate. Run against a sandbox that holds the fund.
TWINBROOK = "0001913724"
TWINBROOK_SIMITREE = ("PIK fact tagged 1.75 instead of 0.0175; the spread was published as the PIK rate and no spread. Printed: "
                      "'SimiTree Acquisition, LLC First lien senior secured ")
SPECS += [
    (TWINBROOK, "2025-12-31", "SimiTree Acquisition, LLC, First lien senior secured term loan",
     {"basis_spread": "5.25", "pik_rate": "1.75"},
     TWINBROOK_SIMITREE + "term loan S + 5.25 % + 1.75 PIK 11.10 % 2/26/2025 5/17/2026 1,239 1,236 1,232 0.05 %'", "D-104"),
    (TWINBROOK, "2025-12-31", "SimiTree Acquisition, LLC, First lien senior secured delayed draw term loan 1",
     {"basis_spread": "5.25", "pik_rate": "1.75"},
     TWINBROOK_SIMITREE + "delayed draw term loan S + 5.25 % + 1.75 PIK 11.10 % 7/28/2023 5/17/2026 4 4 4 0.00 %'", "D-104"),
    (TWINBROOK, "2025-12-31", "SimiTree Acquisition, LLC, First lien senior secured delayed draw term loan 2",
     {"basis_spread": "5.25", "pik_rate": "1.75"},
     TWINBROOK_SIMITREE + "delayed draw term loan S + 5.25 % + 1.75 PIK 11.10 % 2/26/2025 5/17/2026 886 884 881 0.04 %'", "D-104"),
    (TWINBROOK, "2025-12-31", "SimiTree Acquisition, LLC, First lien senior secured revolving loan",
     {"basis_spread": "7", "pik_rate": ""},
     "The margin was published as a PIK rate and no spread; the printed line has no PIK: 'SimiTree Acquisition, LLC First lien "
     "senior secured revolving loan S + 7.00 % 11.10 % 7/28/2023 5/17/2026 178 49 49 0.00 %'", "D-104"),
]
EXACT |= {"SimiTree Acquisition, LLC, First lien senior secured term loan", "SimiTree Acquisition, LLC, First lien senior secured revolving loan"}
# decision D-105: Antares Strategic Credit Fund, two rows whose member names no issuer (2026-10-11)
ANTARES_SC = "0001993402"
ANTARES_SC_WST = ("First Lien Delayed Draw Term Loan Reference Rate and Spread S + 5.25% Interest Rate Floor 1.00% Interest Rate 9.66% "
                  "Maturity Date 3/31/2027")
EXACT.add(ANTARES_SC_WST)
SPECS += [
    (ANTARES_SC, "2024-12-31", ANTARES_SC_WST,
     {"issuer_name": "WST USA Holdco, Inc.", "instrument_description": "First Lien Delayed Draw Term Loan"},
     "The member carries no issuer (context C_d395e38e); the printed line reads 'WST USA Holdco, Inc. (6)(7)(15) First Lien Delayed "
     "Draw Term Loan S + 5.25 % 1.00 % 9.56 % 3/31/2027 2,493 896 910' (Building Products)", "D-105"),
    (ANTARES_SC, "2025-09-30", "Retrieving data. Wait a few seconds and try to cut or copy again.",
     {"issuer_name": "Enverus Holdings, Inc.", "instrument_description": "First Lien Revolver"},
     "The member text is a spreadsheet error message (context C_0b017253); the printed line reads 'Enverus Holdings, Inc. "
     "(7)(15)(17) First Lien Revolver S + 5.50 % 9.63 % 12/24/2029 174 6 7'", "D-105"),
]
# decision D-107: Ares Core Infrastructure Fund, 2025-03-31: the filer put Aspen's unit count on Denali's context (2026-10-11)
ARES_CORE = "0002031750"
ARES_CORE_UNITS = ("The share fact on Denali's context (c-5) holds 4,900, Aspen's units; Aspen's context (c-6) has no share fact. Printed: "
                   "'Aspen Renewables Equity Holdings LLC (1)(5) Ordinary units 03/2025 4,900 $ 407,340 $ 407,340 (2) Denali Equity "
                   "Holdings LLC (1)(5) Class A units 09/2024 3,749 341,183 353,033'")
SPECS += [
    (ARES_CORE, "2025-03-31", "Denali Equity Holdings LLC, Class A units", {"shares_held": "3749"}, ARES_CORE_UNITS, "D-107"),
    (ARES_CORE, "2025-03-31", "Aspen Renewables Equity Holdings LLC, Ordinary units", {"shares_held": "4900"}, ARES_CORE_UNITS, "D-107"),
]
# decision D-110: Sixth Street Specialty Lending, Khoros earnout interests. Their class came from a cache keyed on the full
# member text; with the issuer name split it was lost. The class they were published with is kept (2026-10-12).
SSSL = "0001508655"
for _quarter in ("2025-06-30", "2025-09-30", "2025-12-31"):
    SPECS.append((SSSL, _quarter, "Khoros, LLC Earnout Interests", {"index_classification": "COMMON_EQUITY", "asset_class": "PRIVATE_EQUITY"},
                  "Printed in the Equity and Other Investments section: 'Khoros, LLC ... Earnout Interests'; an equity-type interest "
                  "with no share class word, left unclassified once its name no longer carried the section", "D-110"))
# decision D-100: North Haven Private Income Fund, bare-identifier quarters (to 2025-06-30). Preferred and common
# equity published as loans, and one loan published as a fund. The specs are built from the rows the sandbox still
# shows in the wrong class, so a sandbox built after the corrections adds nothing; rows already written stay.
NH = "0001851322"
NH_PREFERRED = ["FORTIS Solutions Group,  LLC", "FORTIS Solutions Group, LLC", "Integrity Marketing Acquisition, LLC",
                "Knockout Intermediate Holdings I, Inc.", "RSK Holdings, Inc. (Riskonnect)", "Revalize, Inc.",
                "Verdantas LLC 5", "Verdantas, LLC 4", "Verdantas, LLC 5"]
# Printed with a floating rate in the 'Reference Rate and Spread' column ('RSK Holdings, Inc. (Riskonnect) ... Preferred Equity
# S + 10.50 %', 'Revalize, Inc. ... S + 10.00 %'): the tagged spread is a spread and stays. The others print a fixed rate there.
NH_FLOATING_PREFERRED = {"RSK Holdings, Inc. (Riskonnect)", "Revalize, Inc."}
NH_COMMON_2023Q3 = ["Amerilife Holdings, LLC", "Frisbee Holdings, LP (Fetch)", "LUV Car Wash", "Reveal Data Solutions",
                    "Surewerx Topco, LP"]
NH_PREFERRED_REASON = ("Printed under Preferred Equity with a share count and a fixed rate, e.g. 10-K 2024-12-31: 'FORTIS Solutions "
                       "Group, LLC (6) (16) Preferred Equity 12.25 % 06/24/2022 4,000,000 5,064 3,920 0.12', 'Integrity Marketing "
                       "Acquisition, LLC (6) (16) Preferred Equity 10.50 % 07/15/2024 750,000 1,013 998 0.03'; published as a loan, "
                       "the rate held as a spread or the shares as principal")
NH_COMMON_REASON = ("Printed under Common Equity with a share count (10-Q 2023-09-30: 'Amerilife Holdings, LLC (5) (13) 9/1/2022 "
                    "9,880 273 354 0.02 Frisbee Holdings, LP (Fetch) (5) (13) 10/31/2022 28,531 363 363 0.02 LUV Car Wash (5) (13) "
                    "4/6/2022 1,260 1,260 901 0.05 Reveal Data Solutions (5) (13) 8/29/2023 849,231 1,104 1,104 0.06 Surewerx "
                    "Topco, LP (5) (11) (13) 12/28/2022 189 189 204 0.01'); the filer tagged the shares as a principal amount")
NH_TRUGREEN_REASON = ("A first lien loan (par, rate, spread and maturity 11/02/2027 are tagged and printed); classed as a fund "
                      "because the name ends in 'Limited Partnership'")
if NH in held:
    _nh = con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], CAST(bdc_investment_identifier AS VARCHAR), asset_category,
            interest_rate, basis_spread, principal_amount, shares_held
        FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?
          AND CAST(report_date AS VARCHAR)[:10] <= '2025-06-30' AND maturity_date IS NULL AND asset_category = 'LOAN'
          AND CAST(bdc_investment_identifier AS VARCHAR) IN (SELECT unnest(?))
        ORDER BY 1, 2""", [NH, NH_PREFERRED + NH_COMMON_2023Q3]).fetchall()
    for quarter, identifier, category, rate, spread, principal, shares in _nh:
        common = identifier in NH_COMMON_2023Q3
        if common and quarter != "2023-09-30":
            continue
        fields = dict(EQUITY if common else {**PREFERRED, "asset_class": "PRIVATE_EQUITY"})
        if not common and spread is not None and identifier not in NH_FLOATING_PREFERRED:
            if rate is None:
                fields["interest_rate"] = "%g" % spread
            fields["basis_spread"] = ""
            fields.update({"coupon_type": "Fixed", "reference_rate_type": "", "reference_rate_source": ""})
        if shares is None and principal is not None:
            fields["shares_held"] = ("%d" % principal) if float(principal).is_integer() else repr(principal)
            fields["principal_amount"] = ""
        SPECS.append((NH, quarter, identifier, fields, NH_COMMON_REASON if common else NH_PREFERRED_REASON, "D-100"))
        EXACT.add(identifier)
    for (quarter,) in con.execute(f"""SELECT DISTINCT CAST(report_date AS VARCHAR)[:10] FROM read_parquet('{S}/private_markets_holdings.parquet')
            WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(bdc_investment_identifier AS VARCHAR) = 'TruGreen Limited Partnership'
              AND asset_category = 'FUND' ORDER BY 1""", [NH]).fetchall():
        SPECS.append((NH, quarter, "TruGreen Limited Partnership", {"asset_category": "LOAN", "issuer_category": "CORPORATE"},
                      NH_TRUGREEN_REASON, "D-100"))
# decision D-101: Monroe rows of the Equity Securities section whose label names no share class ('..., Equity Securities',
# '(Equity commitment funded) | Equity Securities', '(LLC interest)') are published with category OTHER. Built from the rows
# the sandbox still shows as OTHER; every one of them carries the section or an equity word in its member.
MONROE_EQUITY_REASON = ("The member places the row in the filer's Equity Securities section (or names an equity commitment or LLC "
                        "interest) and names no share class, so it was given no class: ")
if MONROE in held:
    for quarter, identifier in con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], CAST(bdc_investment_identifier AS VARCHAR)
            FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?
              AND asset_category = 'OTHER'
              AND regexp_matches(CAST(bdc_investment_identifier AS VARCHAR), '(?i)equity|LLC interest|profit sharing')
            ORDER BY 1, 2""", [MONROE]).fetchall():
        SPECS.append((MONROE, quarter, identifier, EQUITY, MONROE_EQUITY_REASON + "'" + identifier + "'", "D-101"))
        EXACT.add(identifier)
# decision D-112: Stepstone Private Credit, 10-Q 2026-03-31. Five position contexts are tagged decimals="0" with the printed
# thousands figure as the value, in a schedule whose other facts are decimals="-3": fair value, cost and principal are a
# thousand times too small. Built from the rows the sandbox still shows unscaled (fair value under 10,000).
STEPSTONE = "0001950803"
STEPSTONE_UNSCALED = {
    "C_04d9b75a-b568-46a1-982e-5ed17907b776": "AKAM Buyer, Inc. Term A Loan: printed '2,158 2,126 2,137 0.10 %'",
    "C_f3f8249a-840a-494c-972c-b36dd96ca1b5": "BBG, Inc. Initial Term Loan: printed '6,237 6,131 5,813 0.28 %'",
    "C_c98bc2f5-33ff-4dfc-a955-379f2929fd2c": "Vacation Rental Brands, LLC Amendment No. 2 Incremental Term Loan: printed '2,209 2,189 2,187 0.10 %'",
    "C_8eb7718f-54c7-47ca-a8af-43acd5177a10": "Accelevation LLC Delayed Draw Term Loan: printed '$ 2,380 $ 2,341 $ 2,380 0.11 %'",
    "C_daddbb32-4155-4d60-b813-6dd811efe045": "Accelevation LLC Initial Term Loan: printed '2,848 2,813 2,802 0.13 %'",
}
if STEPSTONE in held:
    for identifier, context, value, cost, principal in con.execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), CAST(src_context_id AS VARCHAR),
            fair_value, cost, principal_amount FROM read_parquet('{S}/private_markets_holdings.parquet')
            WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = '2026-03-31'
              AND CAST(src_context_id AS VARCHAR) IN (SELECT unnest(?)) AND abs(fair_value) < 10000 ORDER BY 1""",
            [STEPSTONE, list(STEPSTONE_UNSCALED)]).fetchall():
        fields = {"fair_value": "%d" % round(value * 1000)}
        if cost is not None:
            fields["cost"] = "%d" % round(cost * 1000)
        if principal is not None:
            fields["principal_amount"] = "%d" % round(principal * 1000)
        SPECS.append((STEPSTONE, "2026-03-31", identifier, fields,
                      "Facts tagged decimals=0 with the thousands figure as the value (context " + context + "); "
                      + STEPSTONE_UNSCALED[context], "D-112"))
        EXACT.add(identifier)
# decision D-117: Stone Point Credit, 10-K 2025-12-31. Three rows whose value cells are tagged decimals="0" with no scale
# attribute (every other row: scale 3): par, cost and fair value are a thousand times too small.
STONEPOINT = "0001825384"
STONEPOINT_UNSCALED = {
    "C_2afcd7c5-7ba2-478a-8ebb-d1154749ee6c": "Helpsystems Holdings, Inc. Second Lien Term Loan: printed '10,175 10,003 8,182 0.6 %'",
    "C_6fa7a5ca-32a6-4b80-ab6f-04110c0fabde": "MRI Software LLC First Lien Delayed Draw Term Loan: printed '1,971 1,929 1,888 0.1 %'",
    "C_a196223c-7936-4dd3-84dc-3ad5991ab90d": "MRI Software LLC First Lien Revolving Loan: printed '506 495 494 0.0 %'",
}
if STONEPOINT in held:
    for identifier, context, value, cost, principal in con.execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), CAST(src_context_id AS VARCHAR),
            fair_value, cost, principal_amount FROM read_parquet('{S}/private_markets_holdings.parquet')
            WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = '2025-12-31'
              AND CAST(src_context_id AS VARCHAR) IN (SELECT unnest(?)) AND abs(fair_value) < 10000 ORDER BY 1""",
            [STONEPOINT, list(STONEPOINT_UNSCALED)]).fetchall():
        fields = {"fair_value": "%d" % round(value * 1000)}
        if cost is not None:
            fields["cost"] = "%d" % round(cost * 1000)
        if principal is not None:
            fields["principal_amount"] = "%d" % round(principal * 1000)
        SPECS.append((STONEPOINT, "2025-12-31", identifier, fields,
                      "Value cells tagged decimals=0 with no scale (context " + context + "); " + STONEPOINT_UNSCALED[context], "D-117"))
        EXACT.add(identifier)
# decision D-134: Crescent Capital BDC. One row tagged on another issuer's member.
SPECS.append(("0001633336", "2026-03-31", "Interest Rate 10.77% Maturity/ Dissolution Date 09/2027 One",
              {"issuer_name": "Safco Dental Supply, LLC", "instrument_description": "Unitranche First Lien Revolver"},
              "Tagged on a Lash Opco member; the page prints the line under Health Care: 'Safco Dental Supply, LLC (5) Unitranche "
              "First Lien Revolver S + 700 ( 400 PIK), 100 Floor 10.77 % 06/2028 342 342 0.0 298' (0001193125-26-221936, context "
              "C_80f8aecd-63d3-4238-8bbc-97543cfa2f21; the maturity tag is 2028-06-30)", "D-134"))
# decision D-127: Bain Capital Private Credit. Facts filed unscaled (decimals 0, the thousands figure as the value).
BAIN = "0001899017"
BAIN_UNSCALED = {  # context prefix: (quarter, fields to scale, printed line)
    "C_22bde640-5d46-4955-8bb8-e49a7f3a69b9": ("2025-09-30", ("fair_value",), "KAMC Holdings, Inc. First Lien Senior Secured Loan: printed '$ 32,926 32,566 32,556'"),
    "C_36e891cf-dc76-4eea-84bf-58986d2ce511": ("2025-09-30", ("fair_value",), "KAMC Holdings, Inc. Revolver: printed '$ 986 944 943'"),
    "C_942fddf9": ("2025-12-31", ("fair_value", "cost", "principal_amount"), "Spotless Brands Delayed Draw: printed '$ 9,618 9,586 9,618'"),
    "C_4f113ac1": ("2025-12-31", ("fair_value", "cost", "principal_amount"), "Spindrift Subordinated Debt: printed '$ 1,574 1,536 1,574'"),
}
if BAIN in held:
    for prefix, (quarter, columns, printed) in BAIN_UNSCALED.items():
        for identifier, context, value, cost, principal in con.execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR),
                CAST(src_context_id AS VARCHAR), fair_value, cost, principal_amount FROM read_parquet('{S}/private_markets_holdings.parquet')
                WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
                  AND starts_with(CAST(src_context_id AS VARCHAR), ?) AND abs(fair_value) < 100000""", [BAIN, quarter, prefix]).fetchall():
            current = {"fair_value": value, "cost": cost, "principal_amount": principal}
            fields = {name: "%d" % round(current[name] * 1000) for name in columns if current[name] is not None and abs(current[name]) < 100000}
            SPECS.append((BAIN, quarter, identifier, fields, "Filed unscaled (context " + context + "); " + printed, "D-127"))
            EXACT.add(identifier)
# decision D-153: two rows of the first five funds read on the page while clearing rule X11
ARES_MURCHISON = "Murchison Oil and Gas, LLC and Murchison Holdings, LLC, First lien senior secured loan"
APOLLO_VERSION1_EUR = ("IT Services Version 1 Investment Company 24 Bidco Limited Investment Type First Lien Secured Debt - Term Loan "
                       "Interest Rate E+490, 0.00% Floor Maturity Date 7/11/2029")
EXACT |= {ARES_MURCHISON, APOLLO_VERSION1_EUR}
SPECS += [
    (ARES, "2024-12-31", ARES_MURCHISON,
     {"asset_category": "EQUITY_PREFERRED", "index_classification": "PREFERRED_EQUITY", "asset_class": "PRIVATE_EQUITY",
      "instrument_description": "Preferred units", "shares_held": "41000"},
     WRONG_MEMBER + "'Murchison Holdings, LLC Exploration and production company Preferred units 06/2022 41,000 - 6.7' "
     "(the loan, 78.3 at 2023-12-31, is no longer on the schedule; the context carries cost 0 and fair value 6.7M)", "D-153"),
    (APOLLO, "2025-12-31", APOLLO_VERSION1_EUR,
     {"principal_amount": "4029000", "principal_amount_currency": "EUR", "principal_amount_usd": "4728434.4",
      "principal_fx_rate_to_usd": "1.1736"},
     "The context carries two principal facts, 6,559,000 in GBP (the sterling term loan's par, printed on the line above) and "
     "4,029,000 in EUR; the first was published. The printed line reads 'First Lien Secured Debt - Term Loan E + 490 , 0.00 % "
     "Floor 7/11/2029 EUR 4,029 3,994 4,711'. Dollar amount at 1.1736, the reference rate the build applies to the fund's other "
     "euro pars on that date (JOA Joker)", "D-153"),
]
for cik, quarter, phrase, fields, reason, *decision in SPECS:
    if cik not in held:
        continue
    author, added_on = (("v05-decision-" + decision[0],
                         "2026-10-13" if "D-145" <= decision[0] < "D-999" and decision[0][2:3] != "0" else
                         "2026-10-11" if decision[0] >= "D-099" or decision[0][2:3] != "0" else
                         "2026-10-09" if decision[0] >= "D-074" else "2026-10-08" if decision[0] >= "D-046" else "2026-10-07")
                        if decision else ("v05-decision-D-021", "2026-10-06"))
    rows = con.execute(f"""SELECT DISTINCT accession_number, CAST(bdc_investment_identifier AS VARCHAR)
        FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?
          AND CAST(report_date AS VARCHAR)[:10] = ?
          AND (contains(CAST(bdc_investment_identifier AS VARCHAR), ?) AND NOT ? OR CAST(bdc_investment_identifier AS VARCHAR) = ?)
          AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL""", [cik, quarter, phrase, phrase in EXACT, phrase]).fetchall()
    # the JV schedule may repeat a name; keep the row the finding is about (cost of 1,000 for Amergin)
    if len(rows) != 1:
        raise SystemExit("expected one row for %s %s %r, found %d: %s" % (cik, quarter, phrase, len(rows), rows[:4]))
    accession, identifier = rows[0]
    for field, value in fields.items():
        key = (cik, quarter, accession, identifier, field)
        if key in existing:
            continue
        writer.writerow([cik, quarter, accession, identifier, field, value, reason,
                         "data/raw/filings/bdc_html/%s/%s.html" % (cik.lstrip("0"), accession.replace("-", "")),
                         author, added_on])
        added += 1
    print("  %s %s %-60s %s" % (cik, quarter, identifier[:60], ", ".join("%s=%s" % kv for kv in fields.items())))
print("corrections to add:", added)
if "--write" in sys.argv and added:
    target.write_bytes(data + (b"" if data.endswith(b"\n") else eol.encode()) + buffer.getvalue().encode("utf-8"))
    print("wrote", target.relative_to(REPO))
