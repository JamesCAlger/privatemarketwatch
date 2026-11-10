"""Read-only: expense, waiver and reimbursement facts filed by a fund for periods ending in a given year (cached companyfacts).

    python scripts/v05_evidence/waivers.py <cik> <year>
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, year = sys.argv[1].zfill(10), sys.argv[2]
sys.path.insert(0, str(REPO))
from pipeline.companyfacts_store import companyfacts_path  # noqa: E402  pinned snapshot

source = companyfacts_path(cik)
if source is None:
    sys.exit("no pinned companyfacts snapshot for " + cik)
facts = json.loads(source.read_text(encoding="utf-8"))["facts"]
want = re.compile(r"waiv|reimburs|expense support|NetExpenses|ExpensesNet|OperatingExpenses$|NetInvestmentIncome$|InvestmentIncomeOperating|GrossInvestmentIncome|Revenues$", re.I)
print("tag | period end | months | value | form")
for taxonomy, tags in facts.items():
    for tag, body in sorted(tags.items()):
        if not want.search(tag):
            continue
        for unit, items in body.get("units", {}).items():
            if unit != "USD":
                continue
            seen = set()
            for item in items:
                end, start = item.get("end", ""), item.get("start", "")
                if not end.startswith(year) or not start:
                    continue
                months = round((int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7]) + 1)
                key = (end, months)
                if key in seen:
                    continue
                seen.add(key)
                print("   %s | %s | %d | %s | %s" % (tag[:70], end, months, format(item["val"], ","), item.get("form")))
