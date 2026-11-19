"""Run one read-only SQL file against the built warehouse and write the result to a CSV file. Diagnostic/export only.
Usage (repo root): warehouse/.venv\Scripts\python.exe warehouse\scripts\slice2\export_csv.py <file.sql> <out.csv>
300-second timeout."""
import csv
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
        rel = con.execute(f.read())
    cols = [d[0] for d in rel.description]
    rows = rel.fetchall()
    with open(out_path, "w", newline="", encoding="ascii", errors="replace") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
    print("rows written:", len(rows))
finally:
    timer.cancel()
    con.close()
