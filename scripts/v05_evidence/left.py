"""Read-only: unresolved ledger rows for given rules in a sandbox: engine | rule | fund | quarter | state | fv at risk | detail."""
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
csv.field_size_limit(10**9)
rules = set(sys.argv[2:])
with open(REPO / "scratch/fund_sandbox" / sys.argv[1] / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    rows = [r for r in csv.DictReader(fh) if r["rule_name"] in rules and r["report_date"][:10] >= "2022"]
if rows:
    print("columns:", ", ".join(rows[0].keys()))
for r in sorted(rows, key=lambda r: (r["rule_name"], r["cik"], r["report_date"])):
    if r["state"].startswith(("dispositioned", "adjudicated_false", "remediated_promoted", "resolved_up", "gone_")):
        continue
    print(" | ".join(str(r.get(k, ""))[:60] for k in ("engine", "rule_name", "cik", "report_date", "state", "fv_at_risk_m", "lane", "review_id")))
