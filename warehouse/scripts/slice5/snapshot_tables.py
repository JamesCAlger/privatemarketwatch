r"""Export every table of the built warehouse (not views, not stored test failures), and the views named on the command
line, to Parquet. Diagnostic only. Copy of scripts/rate_rulings/snapshot_tables.py (slice 5 Task 1) that also exports
named views, so a model that turns from a table into a view (int_field_normalised) is still compared row for row.

Usage (from the repository root):
  warehouse\.venv\Scripts\python.exe warehouse\scripts\slice5\snapshot_tables.py <out dir> <before|after> [<view> ...]

Writes <out dir>/<name>_<suffix>.parquet for each base table in schema main of target/warehouse.duckdb, opened
read-only, and for each named relation (a view or a table; a name that is also a base table is written once). Prints
the names written (the list compare_snapshots.py takes). A named relation that does not exist stops the script.
Base tables whose name starts with a stored-test-failure schema are not in schema main, so they are not exported.
600-second timeout over all relations.
"""
import os
import sys
import threading

import duckdb

out_dir = os.path.abspath(sys.argv[1])
suffix = sys.argv[2]
extra = sys.argv[3:]
os.makedirs(out_dir, exist_ok=True)
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
con = duckdb.connect("target/warehouse.duckdb", read_only=True)
timer = threading.Timer(600, con.interrupt)
timer.start()
try:
    names = [r[0] for r in con.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'main' and table_type = 'BASE TABLE' order by 1").fetchall()]
    known = {r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'main'").fetchall()}
    for name in extra:
        if name not in known:
            raise SystemExit(f"no relation main.{name}")
        if name not in names:
            names.append(name)
    for name in names:
        path = os.path.join(out_dir, f"{name}_{suffix}.parquet").replace("'", "''")
        con.execute(f'copy (select * from main."{name}") to \'{path}\' (format parquet)')
    print(" ".join(names))
finally:
    timer.cancel()
    con.close()
