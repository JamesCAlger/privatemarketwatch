"""Read-only: loan rows of one fund-quarter that carry both a spread and a PIK rate, largest first, to compare with the printed page.

    python scripts/v05_evidence/pik_with_spread.py <label> <cik> <quarter> [rows]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 6
print("fv $M | spread | pik | filed rate | reference | context | id")
for r in duckdb.connect().execute(f"""SELECT round(TRY_CAST(fair_value AS DOUBLE)/1e6,1), basis_spread, pik_rate, interest_rate_reported, reference_rate_type, src_context_id,
        CAST(bdc_investment_identifier AS VARCHAR)[:80] FROM read_parquet('{S}/private_markets_holdings.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ? AND TRY_CAST(pik_rate AS DOUBLE) > 0 AND TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL
      AND coalesce(accounting_record_class,'') <> 'underlying_schedule' ORDER BY TRY_CAST(fair_value AS DOUBLE) DESC LIMIT {limit}""", [sys.argv[2].zfill(10), sys.argv[3]]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
