"""Run one SQL statement (argv[1] or file via @path) in DuckDB, print up to 200 rows. Read-only."""
import sys, duckdb
sql = sys.argv[1]
if sql.startswith("@"):
    sql = open(sql[1:], encoding="utf-8").read()
con = duckdb.connect()
con.execute("SET memory_limit='2GB'")
con.execute("SET threads=4")
M = "C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl"
sql = sql.replace("@M", M)
r = con.execute(sql)
cols = [d[0] for d in r.description]
rows = r.fetchmany(int(sys.argv[2]) if len(sys.argv) > 2 else 200)
print(" | ".join(cols))
for row in rows:
    print(" | ".join("" if v is None else str(v) for v in row))
