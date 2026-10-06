"""Read-only: BCRED published rows of one quarter that carry no reported percent of net assets (schedule rows carry one).

    python scripts/v05_evidence/bcred_nopct_rows.py <label> <quarter>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
print("fv $K | cost $K | principal | units | category | context | id")
for r in duckdb.connect().execute(f"""SELECT round(TRY_CAST(fair_value AS DOUBLE)/1e3), round(TRY_CAST(cost AS DOUBLE)/1e3), principal_amount, shares_held, asset_category, src_context_id,
        CAST(bdc_investment_identifier AS VARCHAR)[:70] FROM read_parquet('{S}/private_markets_holdings.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001803498' AND CAST(report_date AS VARCHAR)[:10] = ? AND coalesce(accounting_record_class,'') <> 'underlying_schedule'
      AND TRY_CAST(pct_of_net_assets AS DOUBLE) IS NULL AND abs(TRY_CAST(fair_value AS DOUBLE)) >= 1e5 ORDER BY abs(TRY_CAST(fair_value AS DOUBLE)) DESC LIMIT 25""", [sys.argv[2]]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
