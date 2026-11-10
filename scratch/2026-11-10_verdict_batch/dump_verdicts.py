"""Print compact verdict content for review ids (argv, or @file of ids) - read-only diagnostic."""
import json, sys
from pathlib import Path
M = Path("C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl")
ids = []
for a in sys.argv[1:]:
    if a.startswith("@"):
        ids += [x.strip() for x in open(a[1:]) if x.strip()]
    else:
        ids.append(a)
for rid in ids:
    for d in (M/"data/output/review_queue/verdicts", M/"data/output/bdc_cik_review/verdicts"):
        p = d / (rid + ".json")
        if p.exists():
            v = json.loads(p.read_text(encoding="utf-8-sig"))
            print("=====", rid, v.get("verdict"), v.get("mechanism"))
            for k in ("observed_value", "anchor_value"):
                print(" ", k, ":", str(v.get(k))[:400])
            for c in v.get("culprit_citations") or []:
                print("   CIT", {k: c.get(k) for k in c if k != "quoted_text"}, "|", str(c.get("quoted_text"))[:300])
            for f in v.get("findings") or []:
                print("   FND", str(f.get("detail"))[:300])
            print("   RAT", str(v.get("rationale"))[:600])
            other = [k for k in v if k not in ("review_id","verdict","mechanism","observed_value","anchor_value","culprit_citations","findings","rationale","localized","anchor_used","confidence","escalate")]
            if other: print("   KEYS", other)
            break
    else:
        print("=====", rid, "NO VERDICT FILE")
