"""Read-only: reconciliation statuses by fund at one quarter, with leaf counts, against output row counts."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, quarter = sys.argv[1], sys.argv[2]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
d = f"read_parquet('{S}/source_reconciliation_detail.parquet')"
print("fund | status | rows | of which wrapper leaf | current period")
for r in con.execute(f"""SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0'), status, count(*),
        count(*) FILTER (WHERE source_wrapper_disposition LIKE '%_position_leaf'), count(*) FILTER (WHERE CAST(period AS VARCHAR)[:10] = CAST(report_date AS VARCHAR)[:10])
    FROM {d} WHERE CAST(report_date AS VARCHAR)[:10] = ? GROUP BY 1,2 ORDER BY 1,3 DESC""", [quarter]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("output rows:", con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0'), count(*), count(*) FILTER (WHERE accounting_record_class <> 'underlying_schedule')
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE CAST(report_date AS VARCHAR)[:10] = ? GROUP BY 1 ORDER BY 1""", [quarter]).fetchall())
