"""Read-only: dump a few ens2 extraction_gap real_error verdict leaves in full,
to characterize what 'extraction_gap' means. ASCII, no network."""
import csv, json
from pathlib import Path

BATCH = Path("data/output/ensemble/ens2")
VER = Path("data/output/review_queue/verdicts")
meta = {r["review_id"]: r for r in csv.DictReader(open(BATCH / "review_ids.csv", encoding="utf-8"))}

hits = []
for rid, m in meta.items():
    p = VER / f"{rid}.json"
    if not p.exists():
        continue
    try:
        v = json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        continue
    if v.get("verdict") == "real_error" and (v.get("mechanism") or "").strip() == "extraction_gap":
        hits.append((rid, m, v))

print("extraction_gap real_errors:", len(hits))
# group by rule to see which rules produce them
from collections import Counter
print("by rule:", Counter(m["rule_name"] for _, m, _ in hits).most_common())
print()
for rid, m, v in hits[:5]:
    print("=" * 72)
    print(rid, "cik", m["cik"], "rule", m["rule_name"], m["report_date"], m["engine"])
    print("observed:", repr(v.get("observed_value")), " anchor:", repr(v.get("anchor_value")))
    print("localized:", v.get("localized"), " anchor_used:", v.get("anchor_used"), " conf:", v.get("confidence"))
    cc = v.get("culprit_citations")
    print("citations:", json.dumps(cc)[:500] if cc else None)
    print("rationale:", (v.get("rationale") or "")[:1100])
    print()
