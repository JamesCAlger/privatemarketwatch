r"""Export the result of one read-only SQL file to a Parquet file. Diagnostic only (fix round 3 guard).

Usage (from the repository root):
  warehouse\.venv\Scripts\python.exe warehouse\scripts\slice2\export_query.py <file.sql> <out.parquet>

Reads target/warehouse.duckdb read-only; writes only the named Parquet file. 300-second timeout.
"""
import os
import sys
import threading

import duckdb

sql_path = os.path.abspath(sys.argv[1])
out_path = os.path.abspath(sys.argv[2])
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
con = duckdb.connect("target/warehouse.duckdb", read_only=True)
timer = threading.Timer(300, con.interrupt)
timer.start()
try:
    with open(sql_path, encoding="utf-8") as f:
        sql = f.read().strip().rstrip(";")
    con.execute("copy (" + sql + ") to '" + out_path.replace("'", "''") + "' (format parquet)")
    print("written:", out_path)
finally:
    timer.cancel()
    con.close()
