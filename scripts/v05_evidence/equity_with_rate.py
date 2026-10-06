"""Read-only: common-equity rows that carry a rate, in a sandbox or the published file: how many, and whether they also carry a maturity and principal.

    python scripts/v05_evidence/equity_with_rate.py <label | published>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "data/output" if sys.argv[1] == "published" else REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE e AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, TRY_CAST(fair_value AS DOUBLE) AS fv,
        maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) NOT IN ('', 'NaT') AS mat, TRY_CAST(principal_amount AS DOUBLE) > 0 AS par,
        CAST(bdc_investment_identifier AS VARCHAR) AS id, CAST(report_date AS VARCHAR)[:10] AS d
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE asset_category = 'EQUITY_COMMON' AND TRY_CAST(interest_rate_reported AS DOUBLE) > 0
      AND bdc_investment_identifier IS NOT NULL AND CAST(report_date AS VARCHAR) >= '2022'""")
print("funds | rows | $M | with maturity and principal: rows | $M | with neither: rows | $M")
print("   " + " | ".join(str(v) for v in con.execute("""SELECT count(DISTINCT cik), count(*), round(sum(fv)/1e6), count(*) FILTER (WHERE mat AND par), round(sum(fv) FILTER (WHERE mat AND par)/1e6),
    count(*) FILTER (WHERE NOT mat AND NOT coalesce(par,false)), round(sum(fv) FILTER (WHERE NOT mat AND NOT coalesce(par,false))/1e6) FROM e""").fetchone()))
print("largest funds: fund | rows | $M | rows with maturity and principal | sample")
for r in con.execute("""SELECT cik, count(*), round(sum(fv)/1e6,1), count(*) FILTER (WHERE mat AND par), arg_max(id[:70], fv) FROM e GROUP BY 1 ORDER BY 2 DESC LIMIT 14""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
