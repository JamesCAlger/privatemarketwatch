"""Read-only: BCRED published rows that could explain a quarter's excess over the filed total: rows with no principal,
no units and no rate facts, with the gap for that quarter.

    python scripts/v05_evidence/bcred_gap_rows.py <label>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost,
        TRY_CAST(principal_amount AS DOUBLE) AS par, TRY_CAST(shares_held AS DOUBLE) AS units, asset_category AS cat, src_context_id AS ctx,
        CAST(bdc_investment_identifier AS VARCHAR) AS id, CAST(bdc_dimensions_raw AS VARCHAR) AS dims,
        regexp_replace(CAST(src_facts AS VARCHAR), ',?"_financial_units".*', '}}') AS facts
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001803498'
      AND coalesce(accounting_record_class,'') <> 'underlying_schedule'""")
con.execute(f"""CREATE TEMP TABLE ff AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, max(TRY_CAST(investments_at_fair_value AS DOUBLE)) AS filed
    FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1) WHERE source = 'companyfacts' AND lpad(CAST(cik AS VARCHAR),10,'0') = '0001803498' GROUP BY 1""")
for d, gap in con.execute("""SELECT d, round((sum(fv) FILTER (WHERE coalesce(cat,'') <> 'CASH') - max(filed))/1e3) FROM h JOIN ff USING (d) GROUP BY 1
        HAVING abs(sum(fv) FILTER (WHERE coalesce(cat,'') <> 'CASH') - max(filed)) > 5e5 ORDER BY 1""").fetchall():
    print("== %s gap $K %s; rows with no principal, units or rate facts: fv $K | cost $K | category | context | id | dims" % (d, gap))
    for r in con.execute("""SELECT round(fv/1e3), round(cost/1e3), cat, ctx, id[:60], dims[:90] FROM h WHERE d = ? AND par IS NULL AND units IS NULL
            AND coalesce(cat,'') <> 'CASH' AND abs(fv) > 1e6 AND NOT contains(facts, 'rate') ORDER BY abs(fv) DESC LIMIT 8""", [d]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
