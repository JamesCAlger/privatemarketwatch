"""Read-only: BCRED published rows that look like footnote figures tagged on an issuer name: no principal, no units,
no rate, no spread, no reported percent of net assets, and cost and fair value both in round 100,000s.
Printed beside each quarter's gap between published and filed totals.

    python scripts/v05_evidence/bcred_footnote_rows.py <label>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
PREDICATE = """TRY_CAST(principal_amount AS DOUBLE) IS NULL AND TRY_CAST(shares_held AS DOUBLE) IS NULL
    AND TRY_CAST(interest_rate_reported AS DOUBLE) IS NULL AND TRY_CAST(basis_spread AS DOUBLE) IS NULL AND TRY_CAST(pik_rate AS DOUBLE) IS NULL
    AND TRY_CAST(pct_of_net_assets AS DOUBLE) IS NULL AND TRY_CAST(fair_value AS DOUBLE) <> 0
    AND TRY_CAST(fair_value AS DOUBLE) % 100000 = 0 AND TRY_CAST(cost AS DOUBLE) % 100000 = 0"""
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT *, CAST(report_date AS VARCHAR)[:10] AS d, ({PREDICATE}) AS hit FROM read_parquet('{S}/private_markets_holdings.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001803498' AND coalesce(accounting_record_class,'') <> 'underlying_schedule'""")
con.execute(f"""CREATE TEMP TABLE ff AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, max(TRY_CAST(investments_at_fair_value AS DOUBLE)) AS filed
    FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1) WHERE source = 'companyfacts' AND lpad(CAST(cik AS VARCHAR),10,'0') = '0001803498' GROUP BY 1""")
print("quarter | gap $K | rows selected | their fv $K | gap after $K | ids")
for r in con.execute("""SELECT d, round((sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE coalesce(asset_category,'') <> 'CASH') - max(filed))/1e3),
        count(*) FILTER (WHERE hit), round(coalesce(sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE hit),0)/1e3),
        round((sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE coalesce(asset_category,'') <> 'CASH' AND NOT hit) - max(filed))/1e3),
        string_agg(CASE WHEN hit THEN CAST(bdc_investment_identifier AS VARCHAR)[:40] || ' ' || CAST(fair_value AS VARCHAR) END, '; ')
    FROM h JOIN ff USING (d) GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
