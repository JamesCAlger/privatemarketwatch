"""Read-only: HPS loan rows with a PIK rate, no filed rate and no spread, by whether a reference rate is known.

    python scripts/v05_evidence/hps_pik_margin.py <label> [cik]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
cik = (sys.argv[2] if len(sys.argv) > 2 else "1838126").zfill(10)
print("reference | rows | $M | lowest pik | highest pik | sample")
for r in duckdb.connect().execute(f"""SELECT coalesce(nullif(trim(CAST(reference_rate_type AS VARCHAR)),''),'(none)'), count(*), round(sum(TRY_CAST(fair_value AS DOUBLE))/1e6,1),
        min(TRY_CAST(pik_rate AS DOUBLE)), max(TRY_CAST(pik_rate AS DOUBLE)), arg_max(CAST(bdc_investment_identifier AS VARCHAR)[:40], TRY_CAST(fair_value AS DOUBLE))
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND asset_category = 'LOAN'
      AND TRY_CAST(pik_rate AS DOUBLE) > 0 AND TRY_CAST(interest_rate_reported AS DOUBLE) IS NULL AND TRY_CAST(basis_spread AS DOUBLE) IS NULL
      AND coalesce(accounting_record_class,'') <> 'underlying_schedule' GROUP BY 1 ORDER BY 2 DESC""", [cik]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
