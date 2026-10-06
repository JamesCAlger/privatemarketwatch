"""Read-only: outstanding findings in a sandbox ledger as a rule x fund matrix (2022 onward)."""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
label = sys.argv[1]
FUNDS = {"0001803498": "BCRED", "0001812554": "OWL", "0001287750": "ARES", "0001838126": "HPS", "0001837532": "APOLLO"}
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated"}
csv.field_size_limit(10**9)
grid = defaultdict(Counter)
states = Counter()
with open(REPO / "scratch/fund_sandbox" / label / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        cik = r["cik"].zfill(10)
        if cik not in FUNDS or r["report_date"][:10] < "2022-01-01" or r["state"] in RESOLVED:
            continue
        grid[(r["engine"], r["rule_name"])][FUNDS[cik]] += 1
        states[r["state"]] += 1
names = list(FUNDS.values())
print("%-18s %-48s %5s | " % ("engine", "rule", "all") + " ".join("%6s" % n for n in names))
total = Counter()
for key, row in sorted(grid.items(), key=lambda kv: -sum(kv[1].values())):
    total.update(row)
    print("%-18s %-48s %5d | " % (key[0][:18], key[1][:48], sum(row.values())) + " ".join("%6s" % (row.get(n) or ".") for n in names))
print("%-18s %-48s %5d | " % ("TOTAL", "", sum(total.values())) + " ".join("%6d" % total[n] for n in names))
print("states:", dict(states))
