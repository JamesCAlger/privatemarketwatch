"""Append the v0.5 row corrections of decision D-021 to data/overrides/row_corrections.csv.

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
BCRED, OWL, HPS, APOLLO = "0001803498", "0001812554", "0001838126", "0001837532"
PREFERRED = {"asset_category": "EQUITY_PREFERRED", "index_classification": "PREFERRED_EQUITY"}
LOAN = {"asset_category": "LOAN", "index_classification": "DIRECT_LENDING", "asset_class": "PRIVATE_CREDIT"}
OPERATING_EQUITY = {"issuer_category": "CORPORATE", "index_classification": "COMMON_EQUITY", "exposure_type": "DIRECT",
                    "asset_class": "PRIVATE_EQUITY"}
AMERGIN = ("Printed under Equity Investments as 'Amergin Asset Management, LLC | Class A Units | 50,000,000 | cost 1'; an operating "
           "company stake, classed as a credit fund interest because the name contains 'Asset Management'")
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
]
con = duckdb.connect()
target = REPO / "data/overrides/row_corrections.csv"
data = target.read_bytes()
eol = "\r\n" if b"\r\n" in data else "\n"
existing = {(r["cik"].zfill(10), r["report_date"], r["accession_number"], r["bdc_investment_identifier"], r["field"])
            for r in csv.DictReader(io.StringIO(data.decode("utf-8")))}
buffer = io.StringIO()
writer = csv.writer(buffer, lineterminator=eol)
added = 0
for cik, quarter, phrase, fields, reason in SPECS:
    rows = con.execute(f"""SELECT DISTINCT accession_number, CAST(bdc_investment_identifier AS VARCHAR)
        FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?
          AND CAST(report_date AS VARCHAR)[:10] = ? AND contains(CAST(bdc_investment_identifier AS VARCHAR), ?)
          AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL""", [cik, quarter, phrase]).fetchall()
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
                         "v05-decision-D-021", "2026-10-06"])
        added += 1
    print("  %s %s %-60s %s" % (cik, quarter, identifier[:60], ", ".join("%s=%s" % kv for kv in fields.items())))
print("corrections to add:", added)
if "--write" in sys.argv and added:
    target.write_bytes(data + (b"" if data.endswith(b"\n") else eol.encode()) + buffer.getvalue().encode("utf-8"))
    print("wrote", target.relative_to(REPO))
