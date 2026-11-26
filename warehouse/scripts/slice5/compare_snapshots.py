r"""Compare before/after Parquet snapshots row by row (slice 5 guard; copy of scripts/slice4/compare_snapshots.py).

Usage (from the repository root):
  warehouse\.venv\Scripts\python.exe warehouse\scripts\slice5\compare_snapshots.py <dir> <name> [<name> ...]

For each name, reads <dir>/<name>_before.parquet and <dir>/<name>_after.parquet in an in-memory DuckDB and prints the
row counts and the number of rows in one and not the other (EXCEPT ALL, so duplicates count). Up to 5 differing rows
of each side are printed. Only the columns of the before file are compared, so a column added later is ignored. A
column whose type differs between the two files is listed (slice 5).
120-second timeout.
"""
import os
import sys
import threading

import duckdb

out_dir = os.path.abspath(sys.argv[1])
names = sys.argv[2:]
con = duckdb.connect()
timer = threading.Timer(120, con.interrupt)
timer.start()
try:
    for name in names:
        b = os.path.join(out_dir, name + "_before.parquet").replace("'", "''")
        a = os.path.join(out_dir, name + "_after.parquet").replace("'", "''")
        cols = [r[0] for r in con.execute(f"describe select * from read_parquet('{b}')").fetchall()]
        sel = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
        nb = con.execute(f"select count(*) from read_parquet('{b}')").fetchone()[0]
        na = con.execute(f"select count(*) from read_parquet('{a}')").fetchone()[0]
        only_b = f"select {sel} from read_parquet('{b}') except all select {sel} from read_parquet('{a}')"
        only_a = f"select {sel} from read_parquet('{a}') except all select {sel} from read_parquet('{b}')"
        cb = con.execute(f"select count(*) from ({only_b})").fetchone()[0]
        ca = con.execute(f"select count(*) from ({only_a})").fetchone()[0]
        # slice 5: also the column types, so a value kept but retyped (a table turned into a view) is seen
        tb = dict((r[0], r[1]) for r in con.execute(f"describe select * from read_parquet('{b}')").fetchall())
        ta = dict((r[0], r[1]) for r in con.execute(f"describe select * from read_parquet('{a}')").fetchall())
        retyped = [f"{c} {tb[c]}->{ta.get(c)}" for c in cols if tb[c] != ta.get(c)]
        print(f"{name}: before {nb} rows, after {na} rows; only before {cb}, only after {ca}; columns {len(cols)}"
              + (f"; types differ: {', '.join(retyped)}" if retyped else ""))
        for label, q, n in (("only before", only_b, cb), ("only after", only_a, ca)):
            if n:
                for r in con.execute(q + " limit 5").fetchall():
                    print("  " + label + ": " + "\t".join("" if v is None else str(v)[:80] for v in r))
finally:
    timer.cancel()
    con.close()
