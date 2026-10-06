"""Read-only: the largest loan rows with a PIK rate, no filed rate and no spread for one fund-quarter.

    python scripts/v05_evidence/pikonly_rows.py <label> <cik> <quarter> [rows]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 8
print("fv $M | pik | reference | accession | context | id")
for r in duckdb.connect().execute(f"""SELECT round(TRY_CAST(fair_value AS DOUBLE)/1e6,2), pik_rate, reference_rate_type, accession_number, src_context_id, CAST(bdc_investment_identifier AS VARCHAR)[:80]
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND asset_class = 'PRIVATE_CREDIT' AND TRY_CAST(pik_rate AS DOUBLE) > 0 AND TRY_CAST(interest_rate_reported AS DOUBLE) IS NULL AND TRY_CAST(basis_spread AS DOUBLE) IS NULL
    ORDER BY TRY_CAST(fair_value AS DOUBLE) DESC LIMIT {limit}""", [sys.argv[2].zfill(10), sys.argv[3]]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
