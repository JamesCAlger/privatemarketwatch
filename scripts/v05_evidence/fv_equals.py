"""Read-only: published rows (any record class) and source rows of a fund-quarter whose fair value in thousands equals a number, or pairs summing to it.

    python scripts/v05_evidence/fv_equals.py <label> <cik> <quarter> <thousands>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, quarter, target = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], float(sys.argv[4]) * 1000
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount AS DOUBLE) AS par,
        accounting_record_class AS cls, asset_category AS cat, src_context_id AS ctx, CAST(bdc_investment_identifier AS VARCHAR) AS id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?""", [cik, quarter])
print("single rows: fv | cost | principal | class | category | context | id")
for r in con.execute("SELECT fv, cost, par, cls, cat, ctx, id[:80] FROM h WHERE abs(abs(fv) - ?) < 600", [target]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("published pairs summing to it: id a (fv) + id b (fv)")
for r in con.execute("""SELECT a.id[:55], a.fv, a.ctx, b.id[:55], b.fv, b.ctx FROM h a JOIN h b ON a.ctx < b.ctx WHERE a.cls <> 'underlying_schedule' AND b.cls <> 'underlying_schedule'
        AND abs(a.fv + b.fv - ?) < 600 AND a.par IS NULL AND b.par IS NULL LIMIT 8""", [target]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
