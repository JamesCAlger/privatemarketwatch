"""Read-only: for one row rule in a sandbox, join its flagged rows to the published file and summarise their shape by fund."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, rule = sys.argv[1], sys.argv[2]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE f AS SELECT h.*, lpad(CAST(h.cik AS VARCHAR),10,'0') AS cik10, CAST(h.report_date AS VARCHAR)[:10] AS d
    FROM read_parquet('{S}/row_validation_issues.parquet') i JOIN read_parquet('{S}/private_markets_holdings.parquet') h ON h.row_id = i.row_id
    WHERE i.rule_id = ? AND CAST(i.report_date AS VARCHAR) >= '2022'""", [rule])
print("fund | quarters | rows | fv <= 0 | 0 < fv < 2 pct of dollar principal | cost <= 0 | no principal | no maturity | sum fv $M | sum |fv| $M | largest |fv| $M")
for r in con.execute("""SELECT cik10, count(DISTINCT d), count(*), count(*) FILTER (WHERE TRY_CAST(fair_value AS DOUBLE) <= 0),
        count(*) FILTER (WHERE TRY_CAST(fair_value AS DOUBLE) > 0 AND TRY_CAST(fair_value AS DOUBLE) < 0.02 * TRY_CAST(principal_amount_usd AS DOUBLE)),
        count(*) FILTER (WHERE TRY_CAST(cost AS DOUBLE) <= 0), count(*) FILTER (WHERE TRY_CAST(principal_amount AS DOUBLE) IS NULL),
        count(*) FILTER (WHERE maturity_date IS NULL), round(sum(TRY_CAST(fair_value AS DOUBLE))/1e6,1), round(sum(abs(TRY_CAST(fair_value AS DOUBLE)))/1e6,1),
        round(max(abs(TRY_CAST(fair_value AS DOUBLE)))/1e6,2) FROM f GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
print("largest by |fv|: fund | quarter | fv | cost | principal usd | rate filed | category | id")
for r in con.execute(f"""SELECT cik10, d, TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), TRY_CAST(principal_amount_usd AS DOUBLE), interest_rate_reported, asset_category,
        CAST(bdc_investment_identifier AS VARCHAR)[:90] FROM f QUALIFY row_number() OVER (PARTITION BY cik10 ORDER BY abs(TRY_CAST(fair_value AS DOUBLE)) DESC) <= {n} ORDER BY 1, 3 DESC""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
