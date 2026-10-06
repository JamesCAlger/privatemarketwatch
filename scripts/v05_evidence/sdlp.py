"""Read-only: Ares Senior Direct Lending Program certificates by quarter: value, cost, principal, accession, context."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
for r in duckdb.connect().execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), TRY_CAST(principal_amount AS DOUBLE),
        accession_number, src_context_id, CAST(bdc_investment_identifier AS VARCHAR)
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001287750'
      AND contains(lower(CAST(bdc_investment_identifier AS VARCHAR)), 'senior direct lending program') ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
