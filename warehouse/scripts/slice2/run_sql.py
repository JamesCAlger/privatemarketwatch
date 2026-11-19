"""Run one read-only SQL file against the built warehouse and print the result. Diagnostic only.

Usage (from the repository root):
  warehouse\\.venv\\Scripts\\python.exe warehouse\\scripts\\slice2\\run_sql.py <file.sql> [max_rows]

The working directory is switched to warehouse/ because the staging views read relative paths.
A 300-second timeout interrupts the query.
"""
import os
import sys
import threading

import duckdb

sql_path = os.path.abspath(sys.argv[1])
max_rows = int(sys.argv[2]) if len(sys.argv) > 2 else 200
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
con = duckdb.connect("target/warehouse.duckdb", read_only=True)
timer = threading.Timer(300, con.interrupt)
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
