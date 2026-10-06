"""Read-only: published rows of a fund-quarter whose identifier starts with a prefix and whose |fair value| in thousands is one of the given numbers; or all rows sorted when none given.

    python scripts/v05_evidence/fv_near.py <label> <cik> <quarter> "<prefix>" [thousands ...]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, quarter, prefix = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], sys.argv[4]
wanted = {int(v) for v in sys.argv[5:]}
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
for identifier, value, cost, ctx in duckdb.connect().execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), src_context_id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND starts_with(lower(CAST(bdc_investment_identifier AS VARCHAR)), lower(?)) ORDER BY 1""", [cik, quarter, prefix]).fetchall():
    k = int(round(abs(value or 0) / 1000))
    if not wanted or k in wanted:
        print("   %s | %s | %s | %s" % (round((value or 0) / 1000), None if cost is None else round(cost / 1000), ctx[-8:], identifier[len(prefix):len(prefix) + 150].strip()))
