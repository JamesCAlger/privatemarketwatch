"""Read-only: run one SQL statement from a file against a sandbox; {S} is the sandbox output folder. Prints at most 80 rows."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
sql = Path(sys.argv[2]).read_text(encoding="utf-8").replace("{S}", S)
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
for statement in [s for s in sql.split(";") if s.strip()]:
    cur = con.execute(statement)
    print(" | ".join(d[0] for d in cur.description))
    for row in cur.fetchmany(80):
        print("   " + " | ".join(str(v) for v in row))
    print()
