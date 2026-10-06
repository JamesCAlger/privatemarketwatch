"""Read-only: fund-financials validation rows for given rules and funds in a sandbox."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label = sys.argv[1]
rules = sys.argv[2].split(",")
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
f = S + "/fund_financials_validation_current.csv"
print([c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_csv('{f}', header=true, all_varchar=true)").fetchall()])
for r in con.execute(f"""SELECT * FROM read_csv('{f}', header=true, all_varchar=true) WHERE check_code IN (SELECT unnest(?)) AND status = 'FAIL'
    AND report_date >= '2022' ORDER BY check_code, cik, report_date""", [rules]).fetchall():
    print("   " + " | ".join(str(v)[:60] for v in r))
