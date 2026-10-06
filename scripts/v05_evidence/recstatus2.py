"""Read-only: where the 'blocking_source...' labels live in a sandbox, and their rows for one fund."""
import glob
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, needle = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
for f in sorted(glob.glob(S + "/source_reconciliation*.csv")):
    cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_csv('{f}', header=true, all_varchar=true)").fetchall()]
    hits = [c for c in cols if con.execute(f"SELECT count(*) FROM read_csv('{f}', header=true, all_varchar=true) WHERE contains(coalesce(\"{c}\",''), ?)", [needle]).fetchone()[0]]
    if not hits or "cik" not in cols:
        continue
    print(Path(f).name, "column", hits[0])
    show = [c for c in ("report_date", "raw_investment_identifier", "investment_identifier", "source_fair_value", "fair_value", "status", "evidence", "reason", "cluster_reason") if c in cols]
    for r in con.execute(f"""SELECT {', '.join(show)} FROM read_csv('{f}', header=true, all_varchar=true) WHERE contains(coalesce("{hits[0]}",''), ?)
        AND lpad(regexp_replace(cik,'[^0-9]','','g'),10,'0') = ? AND report_date >= '2022' ORDER BY 1 LIMIT 20""", [needle, cik]).fetchall():
        print("   " + " | ".join(str(v)[:100] for v in r))
