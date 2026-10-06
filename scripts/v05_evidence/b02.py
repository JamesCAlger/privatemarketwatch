"""Read-only: published rows sharing a position_key in a fund-quarter: distinct tranches or repeated facts?"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label = sys.argv[1]
show = sys.argv[2:]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect(config={"threads": 2, "memory_limit": "4GB"})
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, position_key AS k,
        CAST(bdc_investment_identifier AS VARCHAR) AS id, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(principal_amount AS DOUBLE) AS par,
        CAST(maturity_date AS VARCHAR)[:10] AS mat, CAST(interest_rate_reported AS VARCHAR) AS rate, CAST(basis_spread AS VARCHAR) AS spread,
        position_id, accounting_record_class AS cls
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE nullif(trim(position_key),'') IS NOT NULL""")
con.execute("""CREATE TEMP TABLE g AS SELECT cik, d, k, count(*) n, count(DISTINCT id) ids, count(DISTINCT position_id) pids,
        count(DISTINCT (coalesce(mat,''), coalesce(rate,''), coalesce(spread,''), coalesce(par,-1), coalesce(fv,-1))) variants,
        count(DISTINCT cls) classes, sum(fv) fv
    FROM h GROUP BY 1,2,3 HAVING count(*) > 1""")
print("fund | fund-quarters with repeats | repeated keys | rows | identical identifier | same identifier AND same values | spans schedule classes | distinct position ids = rows")
for r in con.execute("""SELECT cik, count(DISTINCT d), count(*), sum(n), count(*) FILTER (WHERE ids = 1), count(*) FILTER (WHERE ids = 1 AND variants = 1),
        count(*) FILTER (WHERE classes > 1), count(*) FILTER (WHERE pids = n) FROM g GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
for cik in show:
    print("\n== %s last quarter, repeated keys: id | $M | par | maturity | rate | spread | class" % cik)
    for r in con.execute("""SELECT h.id[:130], round(h.fv/1e6,2), h.par, h.mat, h.rate, h.spread, h.cls FROM h JOIN g USING (cik, d, k)
        WHERE h.cik = ? AND h.d = (SELECT max(d) FROM g WHERE cik = ?) ORDER BY h.k, h.id LIMIT 24""", [cik.zfill(10), cik.zfill(10)]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
