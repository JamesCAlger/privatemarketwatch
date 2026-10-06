"""Read-only: count of ledger rows by state and period bucket for a sandbox.

    python scripts/v05_evidence/ledger_states.py <label>
"""
import csv
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
csv.field_size_limit(10**9)
with open(REPO / "scratch/fund_sandbox" / sys.argv[1] / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    rows = list(csv.DictReader(fh))
for (bucket, state), n in sorted(Counter(("2022 on" if r["report_date"][:10] >= "2022" else "before 2022 or undated", r["state"]) for r in rows).items()):
    print("   %-24s %-34s %d" % (bucket, state, n))
