"""Read-only: Blue Owl rows whose value comes from the commitments-table tag, per quarter: rows, sum of value, sum of cost, cost sources."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
print("quarter | rows | sum fv | rows fv < 0 | rows fv > 0 | sum cost | cost sources | largest |fv| row")
for r in duckdb.connect().execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], count(*), sum(TRY_CAST(fair_value AS DOUBLE)), count(*) FILTER (WHERE TRY_CAST(fair_value AS DOUBLE) < 0),
        count(*) FILTER (WHERE TRY_CAST(fair_value AS DOUBLE) > 0), sum(TRY_CAST(cost AS DOUBLE)), CAST(histogram(coalesce(CAST(cost_source AS VARCHAR),'')) AS VARCHAR),
        arg_max(CAST(bdc_investment_identifier AS VARCHAR)[:60] || ' ' || CAST(fair_value AS VARCHAR), abs(TRY_CAST(fair_value AS DOUBLE)))
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001812554'
      AND contains(lower(CAST(src_facts AS VARCHAR)), 'netofunamortizedfees') GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
