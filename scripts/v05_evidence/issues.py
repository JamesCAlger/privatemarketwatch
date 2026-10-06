"""Read-only: row-validation issues for one rule in a sandbox: counts by fund-quarter and sample rows."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, rule = sys.argv[1], sys.argv[2]
cik = sys.argv[3].zfill(10) if len(sys.argv) > 3 else None
S = REPO / "scratch/fund_sandbox" / label / "output"
path = S / "row_validation_issues.parquet"
src = f"read_parquet('{path.as_posix()}')" if path.exists() else f"read_csv('{(S / 'row_validation_issues.csv').as_posix()}', header=true, all_varchar=true)"
con = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
cols = [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + src).fetchall()]
print("columns:", cols)
where = "rule_id = ?" + (" AND lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = '%s'" % cik if cik else "")
print("fund | quarters | rows")
for r in con.execute(f"SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0'), count(DISTINCT CAST(report_date AS VARCHAR)), count(*) FROM {src} WHERE rule_id = ? AND CAST(report_date AS VARCHAR) >= '2022' GROUP BY 1 ORDER BY 1", [rule]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("\nby quarter:")
for r in con.execute(f"SELECT CAST(report_date AS VARCHAR)[:10], count(*) FROM {src} WHERE {where} GROUP BY 1 ORDER BY 1", [rule]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("\nsamples:")
for row in con.execute(f"SELECT * FROM {src} WHERE {where} ORDER BY CAST(report_date AS VARCHAR) DESC LIMIT 6", [rule]).fetchdf().to_dict("records"):
    print("   " + " | ".join("%s=%s" % (k, str(v)[:160]) for k, v in row.items() if str(v) not in ("", "nan", "None", "<NA>")))
