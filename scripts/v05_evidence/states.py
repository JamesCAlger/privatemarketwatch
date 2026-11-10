"""Read-only: outstanding findings in a sandbox ledger by rule and state (2022 onward, five funds)."""
import csv
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated",
            "dispositioned_informational", "dispositioned_as_filed", "dispositioned_not_applicable", "verdict_retired"}
csv.field_size_limit(10**9)
grid = Counter()
with open(REPO / "scratch/fund_sandbox" / sys.argv[1] / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        if r["report_date"][:10] >= "2022-01-01" and r["state"] not in RESOLVED:
            grid[(r["engine"], r["rule_name"], r["state"], r.get("lane", ""))] += 1
for key, n in sorted(grid.items(), key=lambda kv: (kv[0][2], -kv[1])):
    print("%-22s %-10s %-18s %-46s %4d" % (key[2], key[3], key[0][:18], key[1][:46], n))
