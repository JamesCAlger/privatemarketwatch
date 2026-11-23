r"""Like slice2/run_sql.py, but on a named DuckDB file (for example a CI fixture build's ci.duckdb). Diagnostic only.

Usage: warehouse\.venv\Scripts\python.exe warehouse\scripts\slice4\run_sql_on.py <db file> <file.sql> [max_rows]

Opens the database read-only, prints at most max_rows rows (default 200). 120-second timeout.
"""
import sys
import threading

import duckdb

db_path, sql_path = sys.argv[1], sys.argv[2]
max_rows = int(sys.argv[3]) if len(sys.argv) > 3 else 200
con = duckdb.connect(db_path, read_only=True)
timer = threading.Timer(120, con.interrupt)
timer.start()
try:
    with open(sql_path, encoding="utf-8") as f:
        rel = con.execute(f.read())
    cols = [d[0] for d in rel.description]
    rows = rel.fetchmany(max_rows)
    print("\t".join(cols))
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))
    print("-- rows shown:", len(rows))
finally:
    timer.cancel()
    con.close()
