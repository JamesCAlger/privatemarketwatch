"""Read-only: decisive rows for the rate convention: PIK above the filed rate, fully PIK rows, and the same loan in two funds."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d,
        TRY_CAST(interest_rate_reported AS DOUBLE) AS r, TRY_CAST(basis_spread AS DOUBLE) AS s, TRY_CAST(pik_rate AS DOUBLE) AS p,
        TRY_CAST(fair_value AS DOUBLE) AS fv, CAST(bdc_investment_identifier AS VARCHAR) AS id, CAST(maturity_date AS VARCHAR)[:7] AS mat,
        regexp_replace(lower(split_part(split_part(CAST(issuer_name AS VARCHAR), ',', 1), ' and ', 1)), '[^a-z0-9]', '', 'g') AS k, coupon_type
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE asset_class = 'PRIVATE_CREDIT' AND accounting_record_class <> 'underlying_schedule'""")
print("PIK above the filed rate: fund | quarter | filed | pik | spread | $M | id")
for row in con.execute("SELECT cik, d, r, p, s, round(fv/1e6,1), id[:95] FROM h WHERE p > r + 0.01 ORDER BY cik, id, d LIMIT 20").fetchall():
    print("   " + " | ".join(str(v) for v in row))
print("\nfully PIK (filed = PIK), 3 per fund: fund | quarter | filed | pik | spread | coupon | $M | id")
for row in con.execute("""SELECT cik, d, r, p, s, coupon_type, round(fv/1e6,1), id[:80] FROM h WHERE abs(r - p) <= 0.01
    QUALIFY row_number() OVER (PARTITION BY cik ORDER BY fv DESC) <= 3 ORDER BY cik""").fetchall():
    print("   " + " | ".join(str(v) for v in row))
print("\nsame loan (name start, maturity month, spread, PIK) in Ares and in BCRED or HPS, same quarter: pairs | filed rates equal within 0.05 | Ares higher by about the PIK | Ares lower by about the PIK")
for row in con.execute("""SELECT count(*), count(*) FILTER (WHERE abs(a.r - b.r) <= 0.05), count(*) FILTER (WHERE abs(a.r - b.r - a.p) <= 0.1), count(*) FILTER (WHERE abs(b.r - a.r - a.p) <= 0.1)
    FROM h a JOIN h b ON a.d = b.d AND a.k = b.k AND a.mat = b.mat AND a.s = b.s AND a.p = b.p AND length(a.k) >= 6
    WHERE a.cik = '0001287750' AND b.cik IN ('0001803498','0001838126') AND a.p > 0 AND a.r IS NOT NULL AND b.r IS NOT NULL""").fetchall():
    print("   " + " | ".join(str(v) for v in row))
