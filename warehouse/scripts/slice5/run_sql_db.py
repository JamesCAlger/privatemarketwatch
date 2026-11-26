"""Run one read-only SQL file against a named DuckDB file (for example a CI fixture work folder's ci.duckdb) and print
the result. Diagnostic only; the copy of scripts/slice2/run_sql.py with the database as an argument (slice 5 Task 6).

Usage (from the repository root):
  warehouse\\.venv\\Scripts\\python.exe warehouse\\scripts\\slice5\\run_sql_db.py <database.duckdb> <file.sql> [max_rows]

A 120-second timeout interrupts the query.
"""
import os
import sys
import threading

import duckdb

db_path = os.path.abspath(sys.argv[1])
sql_path = os.path.abspath(sys.argv[2])
max_rows = int(sys.argv[3]) if len(sys.argv) > 3 else 200
con = duckdb.connect(db_path, read_only=True)
timer = threading.Timer(120, con.interrupt)
timer.start()
try:
    with open(sql_path, encoding="utf-8") as f:
        sql = f.read()
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    rows = rel.fetchmany(max_rows)
    print("\t".join(cols))
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))
    print("-- rows shown:", len(rows))
finally:
    timer.cancel()
    con.close()
