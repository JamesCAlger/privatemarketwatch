r"""Export every table of the built warehouse (not views, not stored test failures) to Parquet. Diagnostic only.

Usage (from the repository root):
  warehouse\.venv\Scripts\python.exe warehouse\scripts\rate_rulings\snapshot_tables.py <out dir> <before|after>

Writes <out dir>/<table>_<suffix>.parquet for each base table in schema main of target/warehouse.duckdb, opened
read-only, and prints the table names (the list compare_snapshots.py takes). 600-second timeout over all tables.
Rate rulings A and B (2026-11-23): the before/after guard over the whole database, not only the rate tables.
"""
import os
import sys
import threading

import duckdb

out_dir = os.path.abspath(sys.argv[1])
suffix = sys.argv[2]
os.makedirs(out_dir, exist_ok=True)
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
con = duckdb.connect("target/warehouse.duckdb", read_only=True)
timer = threading.Timer(600, con.interrupt)
timer.start()
try:
    names = [r[0] for r in con.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'main' and table_type = 'BASE TABLE' order by 1").fetchall()]
    for name in names:
        path = os.path.join(out_dir, f"{name}_{suffix}.parquet").replace("'", "''")
        con.execute(f'copy (select * from main."{name}") to \'{path}\' (format parquet)')
    print(" ".join(names))
finally:
    timer.cancel()
    con.close()
