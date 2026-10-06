"""Read-only: Apollo rows breaking two weak contracts: principal outside [0, 1e11] and loan maturity before the report date."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
base = f"""FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '{cik}'"""
print("principal outside range: quarter | principal | currency | usd | fv | id")
for r in con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], principal_amount, principal_amount_currency, principal_amount_usd, fair_value, CAST(bdc_investment_identifier AS VARCHAR)[:110]
    {base} AND TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL AND NOT (TRY_CAST(principal_amount AS DOUBLE) BETWEEN 0 AND 1e11) ORDER BY 1 LIMIT 40""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("maturity before report date: quarter | maturity | source | fv | id")
for r in con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], CAST(maturity_date AS VARCHAR)[:10], maturity_date_source, fair_value, CAST(bdc_investment_identifier AS VARCHAR)[:150]
    {base} AND index_classification = 'DIRECT_LENDING' AND TRY_CAST(maturity_date AS DATE) < TRY_CAST(report_date AS DATE) ORDER BY 1 LIMIT 40""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
