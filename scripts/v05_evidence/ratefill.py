"""Read-only: share of loan rows with a rate or spread per fund-quarter, all rows and funded rows only (fair value above zero)."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
print("fund | quarters | quarters under 80 pct (all loan rows) | quarters under 80 pct (funded rows only) | lowest fill all | lowest fill funded")
for r in con.execute(f"""WITH h AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv,
            (TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL OR TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL) AS has
        FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE index_classification = 'DIRECT_LENDING' AND accounting_record_class <> 'underlying_schedule'),
      q AS (SELECT cik, d, avg(CASE WHEN has THEN 1.0 ELSE 0 END) AS a, avg(CASE WHEN has THEN 1.0 ELSE 0 END) FILTER (WHERE fv > 0) AS f FROM h GROUP BY 1,2)
    SELECT cik, count(*), count(*) FILTER (WHERE a < 0.8), count(*) FILTER (WHERE f < 0.8), round(min(a),3), round(min(f),3) FROM q GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
