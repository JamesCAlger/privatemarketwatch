"""Read-only: provenance ledger rows with a given status for one fund in a sandbox.

    python scripts/v05_evidence/prov_status.py <label> <cik> <status> [rows]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
path = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output" / "provenance_ledger.parquet").as_posix()
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 8
con = duckdb.connect()
cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]
status = next(c for c in ("status", "full_status", "final_status") if c in cols)
print("columns:", ", ".join(cols))
where = f"lpad(CAST(cik AS VARCHAR),10,'0') = ? AND {status} = ?"
print(con.execute(f"SELECT field, count(*) FROM read_parquet('{path}') WHERE {where} GROUP BY 1", [sys.argv[2].zfill(10), sys.argv[3]]).fetchall())
for r in con.execute(f"SELECT * FROM read_parquet('{path}') WHERE {where} LIMIT {limit}", [sys.argv[2].zfill(10), sys.argv[3]]).fetchall():
    print("   " + " | ".join(str(v)[:50] for v in r))
