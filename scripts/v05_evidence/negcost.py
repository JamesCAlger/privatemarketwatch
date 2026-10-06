"""Read-only: negative-cost rows by fund and where the cost came from (filed fact or labelled proxy)."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
print("fund | cost source | quarters | rows | sum cost $M | rows with fv <= 0 | first quarter | last quarter")
for r in duckdb.connect().execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0'), coalesce(nullif(CAST(cost_source AS VARCHAR),''),'filed'), count(DISTINCT report_date), count(*),
        round(sum(TRY_CAST(cost AS DOUBLE))/1e6,1), count(*) FILTER (WHERE TRY_CAST(fair_value AS DOUBLE) <= 0), min(CAST(report_date AS VARCHAR)[:10]), max(CAST(report_date AS VARCHAR)[:10])
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE TRY_CAST(cost AS DOUBLE) < 0 AND coalesce(accounting_record_class,'') <> 'underlying_schedule'
    GROUP BY 1,2 ORDER BY 1,2""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
