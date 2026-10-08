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
]
# Phrases that are a whole identifier and also the start of another ('... secured loan' and '... secured loan 2').
EXACT = {"UP Intermediate II LLC and UPBW Blocker LLC, First lien senior secured loan",
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
for cik, quarter, phrase, fields, reason, *decision in SPECS:
    author, added_on = (("v05-decision-" + decision[0], "2026-10-08" if decision[0] >= "D-046" else "2026-10-07")
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
