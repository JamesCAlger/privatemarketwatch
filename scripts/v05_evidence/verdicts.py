"""Read-only: the recorded verdict behind each unresolved finding in a sandbox ledger.

    python scripts/v05_evidence/verdicts.py <label> [chars]
"""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import findings_ledger as fl  # noqa: E402

csv.field_size_limit(10**9)
width = int(sys.argv[2]) if len(sys.argv) > 2 else 700
DONE = ("dispositioned", "adjudicated_false", "remediated_promoted", "resolved_up", "gone_")
with open(REPO / "scratch/fund_sandbox" / sys.argv[1] / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    rows = [r for r in csv.DictReader(fh) if r["report_date"][:10] >= "2022" and not r["state"].startswith(DONE)]
dirs = [Path(d) for d in fl.VERDICT_DIRS]
if not dirs:
    dirs = [p for p in (REPO / "data/output").rglob("verdicts") if p.is_dir()]
index = {}
for folder in dirs:
    for path in folder.glob("*.json"):
        index.setdefault(path.stem, path)
for r in sorted(rows, key=lambda r: (r["rule_name"], r["cik"], r["report_date"])):
    print("\n== %s %s %s %s | %s | %s" % (r["rule_name"], r["cik"], r["report_date"][:10], r["state"], r["review_id"], r.get("verdict_detail", "")[:120]))
    path = index.get(r["review_id"])
    if not path:
        print("   (no verdict file found)")
        continue
    try:
        body = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        print("   (unreadable) " + str(path))
        continue
    keep = {k: v for k, v in body.items() if k not in ("review_id", "cik", "rule_name", "report_date", "schema_version", "engine", "lane")}
    print("   " + json.dumps(keep or body, ensure_ascii=True)[:width])
