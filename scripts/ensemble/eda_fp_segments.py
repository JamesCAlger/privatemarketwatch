"""Read-only: for the high-FP weak rules, dump false_alarm vs real_error
rationales + mechanisms to see whether the FPs cluster in a separable segment
(asset class, instrument type, source, sign convention) the rule could exclude.
ASCII, no network, ens2 batch only."""
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

BATCH = Path("data/output/ensemble/ens2")
VER = Path("data/output/review_queue/verdicts")
TARGETS = {"C404", "PCT01", "fmt_cost", "pct_position_concentration", "X08", "FX01", "PP01"}

meta = {r["review_id"]: r for r in csv.DictReader(open(BATCH / "review_ids.csv", encoding="utf-8"))}
byrule = defaultdict(lambda: {"false_alarm": [], "real_error": [], "other": []})
for rid, m in meta.items():
    if m["rule_name"] not in TARGETS:
        continue
    p = VER / f"{rid}.json"
    if not p.exists():
        continue
    try:
        v = json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        continue
    verd = (v.get("verdict") or "").lower()
    bucket = verd if verd in ("false_alarm", "real_error") else "other"
    byrule[m["rule_name"]][bucket].append(v)

for rule in sorted(byrule):
    b = byrule[rule]
    print("=" * 74)
    print(f"{rule}: FA={len(b['false_alarm'])}  real={len(b['real_error'])}  other={len(b['other'])}")
    print("  FA mechanisms:", Counter((x.get('mechanism') or '').strip() for x in b['false_alarm']).most_common())
    print("  sample FALSE_ALARM rationales:")
    for v in b['false_alarm'][:3]:
        print("    -", (v.get('rationale') or '')[:260].replace("\n", " "))
    if b['real_error']:
        print("  sample REAL_ERROR rationales:")
        for v in b['real_error'][:2]:
            print("    +", (v.get('rationale') or '')[:260].replace("\n", " "))
    print()
