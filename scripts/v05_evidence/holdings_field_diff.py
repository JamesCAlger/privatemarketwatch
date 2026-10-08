"""Read-only: every published field that differs between two sandboxes, by column and fund.

    python scripts/v05_evidence/holdings_field_diff.py <label> <label before>

Rows are matched on row_id. A change to a field no fix was aimed at shows here and nowhere else:
the findings ledger has no rule for a lost lien, unit count or class.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
FUNDS = {"0001803498": "BCRED", "0001812554": "Blue Owl", "0001287750": "Ares", "0001838126": "HPS", "0001837532": "Apollo"}
new, old = sys.argv[1], sys.argv[2]
path = lambda label: (REPO / "scratch/fund_sandbox" / label / "output/private_markets_holdings.parquet").as_posix()
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
con.execute(f"CREATE TEMP TABLE a AS SELECT * FROM read_parquet('{path(new)}')")
con.execute(f"CREATE TEMP TABLE b AS SELECT * FROM read_parquet('{path(old)}')")
columns = [r[0] for r in con.execute("DESCRIBE a").fetchall()]
shared = [c for c in columns if c in {r[0] for r in con.execute("DESCRIBE b").fetchall()} and c != "row_id"]
print("rows: %s %d, %s %d; only in %s %d, only in %s %d" % (
    new, con.execute("SELECT count(*) FROM a").fetchone()[0], old, con.execute("SELECT count(*) FROM b").fetchone()[0],
    new, con.execute("SELECT count(*) FROM a ANTI JOIN b USING (row_id)").fetchone()[0],
    old, con.execute("SELECT count(*) FROM b ANTI JOIN a USING (row_id)").fetchone()[0]))
print("column | rows that differ | by fund | example (before -> after)")
quiet = 0
for column in shared:
    rows = con.execute(f"""SELECT lpad(CAST(a.cik AS VARCHAR), 10, '0'), count(*), any_value(CAST(b."{column}" AS VARCHAR)), any_value(CAST(a."{column}" AS VARCHAR))
        FROM a JOIN b USING (row_id) WHERE CAST(a."{column}" AS VARCHAR) IS DISTINCT FROM CAST(b."{column}" AS VARCHAR) GROUP BY 1 ORDER BY 1""").fetchall()
    if not rows:
        quiet += 1
        continue
    print("   %s | %d | %s | %s -> %s" % (column, sum(r[1] for r in rows), ", ".join("%s %d" % (FUNDS.get(r[0], r[0]), r[1]) for r in rows),
                                         str(rows[0][2])[:40].encode("ascii", "replace").decode(), str(rows[0][3])[:40].encode("ascii", "replace").decode()))
print("columns with no difference: %d of %d" % (quiet, len(shared)))
