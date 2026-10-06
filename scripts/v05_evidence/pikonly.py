"""Read-only: loan rows with a PIK rate and no filed rate, by fund: with and without a spread, reference rate known or not, value.

    python scripts/v05_evidence/pikonly.py <label>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv,
        TRY_CAST(pik_rate AS DOUBLE) AS pik, TRY_CAST(basis_spread AS DOUBLE) AS spread, TRY_CAST(interest_rate_reported AS DOUBLE) AS filed,
        TRY_CAST(interest_rate AS DOUBLE) AS rate, nullif(trim(CAST(reference_rate_type AS VARCHAR)),'') AS ref, CAST(bdc_investment_identifier AS VARCHAR) AS id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE asset_class = 'PRIVATE_CREDIT' AND coalesce(accounting_record_class,'') <> 'underlying_schedule'""")
print("fund | rows with PIK and no filed rate | $M | no spread: rows | $M | of those published with a rate | reference rate known | with spread: rows | $M")
for r in con.execute("""SELECT cik, count(*), round(sum(fv)/1e6), count(*) FILTER (WHERE spread IS NULL), round(sum(fv) FILTER (WHERE spread IS NULL)/1e6),
        count(*) FILTER (WHERE spread IS NULL AND rate IS NOT NULL), count(*) FILTER (WHERE spread IS NULL AND ref IS NOT NULL),
        count(*) FILTER (WHERE spread IS NOT NULL), round(sum(fv) FILTER (WHERE spread IS NOT NULL)/1e6)
    FROM h WHERE pik > 0 AND filed IS NULL GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("Blue Owl, latest quarter, PIK and no spread: $M | pik | reference | id")
for r in con.execute("""SELECT round(fv/1e6,1), pik, ref, id[:90] FROM h WHERE cik = '0001812554' AND pik > 0 AND filed IS NULL AND spread IS NULL
      AND d = (SELECT max(d) FROM h WHERE cik = '0001812554') ORDER BY fv DESC LIMIT 14""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
