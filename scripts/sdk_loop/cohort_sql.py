"""Read-only: run one SQL statement from a file against the published outputs; {P} is data/output.

    python scripts/sdk_loop/cohort_sql.py <file.sql>

The statement is screened by scripts/sdk_review/tools.sql_problem before it gets here; this script
opens DuckDB in memory with a 3 GB limit and prints at most 200 rows.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
P = (REPO / "data" / "output").as_posix()
sql = Path(sys.argv[1]).read_text(encoding="utf-8").replace("{P}", P)
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
cur = con.execute(sql)
print(" | ".join(d[0] for d in cur.description))
for row in cur.fetchmany(200):
    print("   " + " | ".join(str(v) for v in row))
