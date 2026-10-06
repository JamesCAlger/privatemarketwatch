"""Read-only: Ares current-period source rows that carry a quantity but no fair value, by quarter."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE s AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, trim(CAST(investment_identifier AS VARCHAR)) AS id, TRY_CAST(fair_value AS DOUBLE) AS fv,
        TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount AS DOUBLE) AS par, TRY_CAST(shares_held AS DOUBLE) AS sh, src_context_id
    FROM read_parquet('{S}/bdc_holdings.parquet') WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = '0001287750'
      AND CAST(period AS VARCHAR)[:10] = CAST(report_date AS VARCHAR)[:10]""")
print("quarter | rows with a quantity and no fair value | of which also no cost | with units | with principal")
for r in con.execute("""SELECT d, count(*), count(*) FILTER (WHERE cost IS NULL), count(sh), count(par) FROM s WHERE fv IS NULL AND (par IS NOT NULL OR sh IS NOT NULL)
    AND regexp_matches(id, ',') GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
for q in sys.argv[2:]:
    print("==", q, ": id | units | principal | context")
    for r in con.execute("SELECT id[:110], sh, par, src_context_id FROM s WHERE d = ? AND fv IS NULL AND cost IS NULL AND (par IS NOT NULL OR sh IS NOT NULL) AND regexp_matches(id, ',') ORDER BY 1 LIMIT 40", [q]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
