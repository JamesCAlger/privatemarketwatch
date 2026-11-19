"""Like run_sql.py, but sets DuckDB variables first: run_sql_vars.py <file.sql> <max_rows> name=value ...
Values that look like integers are set as integers. Diagnostic only; 300-second timeout."""
import os
import sys
import threading

import duckdb

sql_path = os.path.abspath(sys.argv[1])
max_rows = int(sys.argv[2])
pairs = [a.split("=", 1) for a in sys.argv[3:]]
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
con = duckdb.connect("target/warehouse.duckdb", read_only=True)
timer = threading.Timer(300, con.interrupt)
timer.start()
try:
    for k, v in pairs:
        val = v if not v.lstrip("-").isdigit() else int(v)
        con.execute(f"set variable {k} = ?", [val])
    with open(sql_path, encoding="utf-8") as f:
        sql = f.read()
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    rows = rel.fetchmany(max_rows)
    print("\t".join(cols))
    for r in rows:
        print("\t".join("" if v is None else str(v)[:600] for v in r))
    print("-- rows shown:", len(rows))
finally:
    timer.cancel()
    con.close()
