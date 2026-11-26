"""Text slice R: rows by how far the proposed reading of their shape is supported. Usage: python summarise_proposals.py <run_dir>
A shape is: unstable (the two option orders differ), contradicted (a number role disagrees with the tags on 5+ rows),
confirmed (every role that a tag can test is confirmed on 90%+ of 5+ compared rows), untested (stable, but no tag
exists to test any role), no_number (a shape with no number: a code or a word only). Floors have no tag anywhere."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

run = Path(sys.argv[1])
ROLE = {"spread_bps": ("spread", "equal_bps"), "spread_pct": ("spread", "equal"), "all_in_rate_pct": ("interest_rate", "equal"),
        "cash_rate_pct": ("interest_rate_cash", "equal"), "pik_rate_pct": ("pik_rate", "equal"), "pik_spread_pct": ("pik_rate", "equal")}
rows, shapes = Counter(), Counter()
per_col = defaultdict(Counter)
for bp in sorted((run / "bundles").glob("*.json")):
    b = json.loads(bp.read_text(encoding="utf-8"))
    p = {o: json.loads((run / "proposals" / f"{bp.stem}_{o}.json").read_text(encoding="utf-8")) for o in ("fwd", "rev")}
    if p["fwd"]["column_holds"] != p["rev"]["column_holds"]:
        print("COLUMN ORDERS DIFFER", bp.stem, b["header_text"], p["fwd"]["column_holds"], p["rev"]["column_holds"])
    sf = {s["shape"]: s.get("roles", []) for s in p["fwd"].get("shapes", [])}
    sr = {s["shape"]: s.get("roles", []) for s in p["rev"].get("shapes", [])}
    for s in b["shapes"]:
        k, n = s["shape"], s["shape"].count("#")
        a, c = sf.get(k), sr.get(k)
        if n == 0:
            st = "no_number"
        elif a is None or a != c or len(a) != n:
            st = "unstable"
        else:
            ok = bad = 0
            for i, role in enumerate(a, 1):
                if role not in ROLE:
                    continue
                fld, col = ROLE[role]
                for leg in s.get("legs") or []:
                    if leg["number"] == f"n{i}" and leg["field"] == fld and leg["compared"] >= 5:
                        if leg[col] / leg["compared"] >= 0.9:
                            ok += 1
                        else:
                            bad += 1
            st = "contradicted" if bad else "confirmed" if ok else "untested"
        rows[st] += s["rows"]
        shapes[st] += 1
        per_col[(p["fwd"]["column_holds"])][st] += s["rows"]
tot = sum(rows.values())
for st in ("confirmed", "untested", "no_number", "unstable", "contradicted"):
    print(f"{st:13s} shapes {shapes[st]:4d}  rows {rows[st]:7d}  {100 * rows[st] / tot:5.1f}%")
print("by column kind (rows):")
for k, c in sorted(per_col.items()):
    print(f"  {k:20s}", dict(c))
