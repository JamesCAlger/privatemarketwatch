"""Which funds' published rows moved between two builds, field by field.

The findings ledger only sees what a rule flags. A change that alters a fund's values without
tripping a rule (a lost lien, a unit count, a class, a rate) shows here and nowhere else. A batch
compares its holdings with the previous batch's and lists every fund that moved; a fund no recorded
fix named is unexplained until someone explains it.

Rows are matched on ``row_id`` (hash of accession and context, stable across builds). One DuckDB
pass over both Parquet files; nothing is loaded into pandas.
"""
from __future__ import annotations

from pathlib import Path

COLUMNS = ["cik", "rows", "rows_before", "rows_added", "rows_removed", "rows_changed", "fair_value",
           "fair_value_before", "fair_value_change", "changed_fields", "moved", "named_by_fix"]
KEY = "row_id"
PAD = "lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"


def compare(new_path: Path, old_path: Path, *, named_ciks=(), ignore: tuple[str, ...] = (),
            memory_limit: str = "4GB") -> list[dict]:
    """One row per fund in either build. ``named_ciks``: funds a recorded fix expected to change
    ('*' names every fund, for a declared shared-code change). ``ignore``: columns not compared."""
    import duckdb

    new_sql, old_sql = Path(new_path).as_posix(), Path(old_path).as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='%s'" % memory_limit)
        new_cols = [r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet('%s')" % new_sql).fetchall()]
        old_cols = {r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet('%s')" % old_sql).fetchall()}
        for required in (KEY, "cik", "fair_value"):
            if required not in new_cols or required not in old_cols:
                raise ValueError("holdings file has no %s column" % required)
        shared = [c for c in new_cols if c in old_cols and c not in (KEY, "cik") and c not in ignore]
        differs = ['CAST(a."%s" AS VARCHAR) IS DISTINCT FROM CAST(b."%s" AS VARCHAR)' % (c, c) for c in shared]
        per_field = ", ".join("count_if(%s) AS f%d" % (d, i) for i, d in enumerate(differs)) or "0 AS f0"
        any_field = " OR ".join(differs) or "false"
        changed = con.execute(
            "SELECT %s AS cik, count_if(%s) AS rows_changed, %s FROM read_parquet('%s') a JOIN read_parquet('%s') b "
            "USING (%s) GROUP BY 1" % (PAD.replace("cik", "a.cik"), any_field, per_field, new_sql, old_sql, KEY)).fetchall()
        totals = {}
        for side, sql in (("new", new_sql), ("old", old_sql)):
            for cik, rows, fv in con.execute(
                    "SELECT %s, count(*), coalesce(sum(TRY_CAST(fair_value AS DOUBLE)), 0) FROM read_parquet('%s') GROUP BY 1"
                    % (PAD, sql)).fetchall():
                totals.setdefault(cik, {})[side] = (rows, fv)
        added = dict(con.execute("SELECT %s, count(*) FROM read_parquet('%s') a ANTI JOIN read_parquet('%s') b USING (%s) GROUP BY 1"
                                 % (PAD.replace("cik", "a.cik"), new_sql, old_sql, KEY)).fetchall())
        removed = dict(con.execute("SELECT %s, count(*) FROM read_parquet('%s') a ANTI JOIN read_parquet('%s') b USING (%s) GROUP BY 1"
                                   % (PAD.replace("cik", "a.cik"), old_sql, new_sql, KEY)).fetchall())
    finally:
        con.close()
    fields = {}
    for row in changed:
        counts = [(shared[i], n) for i, n in enumerate(row[2:2 + len(shared)]) if n]
        fields[row[0]] = (row[1], ";".join("%s:%d" % item for item in sorted(counts, key=lambda kv: (-kv[1], kv[0]))))
    named = {str(c).zfill(10) for c in named_ciks if c != "*"}
    everyone = "*" in set(named_ciks)
    out = []
    for cik in sorted(totals):
        rows_new, fv_new = totals[cik].get("new", (0, 0.0))
        rows_old, fv_old = totals[cik].get("old", (0, 0.0))
        rows_changed, changed_fields = fields.get(cik, (0, ""))
        moved = bool(added.get(cik) or removed.get(cik) or rows_changed)
        out.append({"cik": cik, "rows": rows_new, "rows_before": rows_old, "rows_added": added.get(cik, 0),
                    "rows_removed": removed.get(cik, 0), "rows_changed": rows_changed,
                    "fair_value": round(fv_new, 2), "fair_value_before": round(fv_old, 2),
                    "fair_value_change": round(fv_new - fv_old, 2), "changed_fields": changed_fields,
                    "moved": moved, "named_by_fix": everyone or cik in named})
    return out


def summarize(rows: list[dict]) -> dict:
    moved = [r for r in rows if r["moved"]]
    unexplained = [r["cik"] for r in moved if not r["named_by_fix"]]
    return {"funds": len(rows), "funds_moved": len(moved), "funds_moved_unexplained": len(unexplained),
            "unexplained_ciks": unexplained[:80],
            "fair_value_change": round(sum(r["fair_value_change"] for r in rows), 2)}
