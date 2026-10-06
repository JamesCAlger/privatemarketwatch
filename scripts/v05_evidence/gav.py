"""Read-only: GAV reconciliation rows for one fund in a sandbox."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
f = S + "/holdings_gav_reconciliation.csv"
cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_csv('{f}', header=true, all_varchar=true)").fetchall()]
print(cols)
for r in con.execute(f"SELECT * FROM read_csv('{f}', header=true, all_varchar=true) WHERE lpad(regexp_replace(cik,'[^0-9]','','g'),10,'0') = ? AND report_date >= '2023' ORDER BY report_date", [cik]).fetchall():
    print("   " + " | ".join(str(v)[:26] for v in r))
