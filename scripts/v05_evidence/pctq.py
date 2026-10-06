"""Read-only: reported percent of net assets by quarter for one fund: fill, sum, calculated sum, and scale against the calculated value."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
print("quarter | rows | with reported pct | reported sum | calculated sum (all rows) | calculated sum (rows with reported) | median reported/calculated | rows where reported is over 20x calculated | under 1/20")
for r in con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], count(*), count(p), round(sum(p),2), round(sum(c),2), round(sum(c) FILTER (WHERE p IS NOT NULL),2),
        round(median(p/nullif(c,0)),3), count(*) FILTER (WHERE p/nullif(c,0) > 20), count(*) FILTER (WHERE p/nullif(c,0) < 0.05 AND p <> 0)
    FROM (SELECT report_date, TRY_CAST(pct_of_net_assets AS DOUBLE) AS p, TRY_CAST(pct_of_net_assets_calculated AS DOUBLE) AS c
          FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND accounting_record_class <> 'underlying_schedule')
    GROUP BY 1 ORDER BY 1""", [cik]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
