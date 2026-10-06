"""Read-only: fund-level income, gross and net expenses by quarter for one fund in a sandbox, with the identity gap.

    python scripts/v05_evidence/netexp.py <label> <cik>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
print("quarter | NII | income | gross expenses | net expenses | gap using net-or-gross | gap / income")
for r in duckdb.connect().execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], TRY_CAST(net_investment_income AS DOUBLE), TRY_CAST(total_investment_income AS DOUBLE),
        TRY_CAST(total_expenses AS DOUBLE), TRY_CAST(net_expenses AS DOUBLE),
        TRY_CAST(net_investment_income AS DOUBLE) - (TRY_CAST(total_investment_income AS DOUBLE) - coalesce(TRY_CAST(net_expenses AS DOUBLE), TRY_CAST(total_expenses AS DOUBLE))),
        round((TRY_CAST(net_investment_income AS DOUBLE) - (TRY_CAST(total_investment_income AS DOUBLE) - coalesce(TRY_CAST(net_expenses AS DOUBLE), TRY_CAST(total_expenses AS DOUBLE)))) / nullif(TRY_CAST(total_investment_income AS DOUBLE),0), 3)
    FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1) WHERE source = 'companyfacts' AND lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR) >= '2022' ORDER BY 1""", [sys.argv[2].zfill(10)]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
