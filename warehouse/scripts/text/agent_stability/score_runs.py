"""Score blind answer files against the 2026-11-19 reference labels and against each other.
Usage: python score_runs.py <dir>   (reads <dir>/answers/*.json and <dir>/reference_results.csv)"""
import csv
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

base = Path(sys.argv[1])
ref = {}
with open(base / "reference_results.csv", encoding="utf-8", newline="") as fh:
    for r in csv.DictReader(fh):
        ref[r["item_id"]] = (r["kind"], r["basis"], r["r1_ref"] if r["kind"] == "rate" else r["ref"])
runs = {}
for p in sorted((base / "answers").glob("*.json")):
    rows = json.loads(p.read_text(encoding="utf-8-sig"))
    runs[p.stem] = {a["item_id"]: (a["answer"], float(a.get("confidence", 0))) for a in rows}
strong = [i for i, v in ref.items() if v[1] == "strong"]
print("items", len(ref), "strong", len(strong), Counter(ref[i][0] for i in strong))
for name, ans in runs.items():
    c = Counter()
    for i in strong:
        k = ref[i][0]
        a = ans.get(i)
        c[(k, "n")] += 1
        if a is None:
            c[(k, "missing")] += 1
            continue
        c[(k, "ok")] += a[0] == ref[i][2]
        c[(k, "cannot_tell")] += a[0] == "cannot_tell"
        if a[1] >= 0.9 and a[0] != "cannot_tell":
            c[(k, "acc09")] += 1
            c[(k, "acc09_ok")] += a[0] == ref[i][2]
    tot = {m: sum(v for (k, mm), v in c.items() if mm == m) for m in ("n", "ok", "cannot_tell", "acc09", "acc09_ok", "missing")}
    print(name, "answered", len(ans), "ALL", tot, {k: (c[(k, "ok")], c[(k, "n")]) for k in ("header", "heading", "rate")})
for a, b in combinations(runs, 2):
    both = [i for i in ref if i in runs[a] and i in runs[b]]
    same = sum(runs[a][i][0] == runs[b][i][0] for i in both)
    sb = [i for i in strong if i in runs[a] and i in runs[b]]
    agree = [i for i in sb if runs[a][i][0] == runs[b][i][0] and runs[a][i][0] != "cannot_tell"]
    ok = sum(runs[a][i][0] == ref[i][2] for i in agree)
    print(f"PAIR {a} vs {b}: same {same}/{len(both)} of all items; on strong: agree {len(agree)}/{len(sb)}, of which correct {ok}")
if len(runs) >= 2:
    sb = [i for i in strong if all(i in r for r in runs.values())]
    allsame = [i for i in sb if len({r[i][0] for r in runs.values()}) == 1 and next(iter(runs.values()))[i][0] != "cannot_tell"]
    ok = sum(next(iter(runs.values()))[i][0] == ref[i][2] for i in allsame)
    print(f"ALL {len(runs)} RUNS AGREE on strong: {len(allsame)}/{len(sb)}, of which correct {ok}")
    for i in sb:
        if i not in allsame or next(iter(runs.values()))[i][0] != ref[i][2]:
            print("  DIFF", ref[i][0], i, "ref=" + ref[i][2], {n: r[i][0] for n, r in runs.items()})
