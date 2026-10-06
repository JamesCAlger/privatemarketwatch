"""Read-only: one finding family in a sandbox: shadow-ledger rows by fund, with metric and mechanism."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, rules = sys.argv[1], sys.argv[2:]
S = REPO / "scratch/fund_sandbox" / label / "output"
con = duckdb.connect(config={"threads": 2, "memory_limit": "2GB"})
led = "read_csv('%s', header=true, all_varchar=true)" % str(S / "shadow/validation_results_ledger.csv").replace("\\", "/")
print("shadow columns:", [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + led).fetchall()])
for rule in rules:
    print("\n== %s: fund | status | quarters | metric min..max | metric_name | n_units sum | mechanism | confidence" % rule)
    for row in con.execute(f"""SELECT lpad(cik,10,'0'), status, count(*), round(min(TRY_CAST(metric AS DOUBLE)),3),
            round(max(TRY_CAST(metric AS DOUBLE)),3), any_value(metric_name), sum(TRY_CAST(n_units AS BIGINT)),
            any_value(mechanism), any_value(confidence)
        FROM {led} WHERE rule_name = ? AND period >= '2022-01-01' AND status IN ('fail','warn') GROUP BY 1, 2 ORDER BY 1""",
                           [rule]).fetchall():
        print("   " + " | ".join(str(v) for v in row))
