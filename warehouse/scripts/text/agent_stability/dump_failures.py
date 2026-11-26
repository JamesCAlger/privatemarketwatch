"""List every strong-label item where any run disagrees with the reference label, with its context.
Usage: python dump_failures.py <api_dir> <subagent_dir>"""
import csv
import json
import sys
from pathlib import Path

api, sub = Path(sys.argv[1]), Path(sys.argv[2])
ref = {}
with open(api / "reference_results.csv", encoding="utf-8", newline="") as fh:
    for r in csv.DictReader(fh):
        ref[r["item_id"]] = r
runs = {}
for tag, d in (("api", api), ("sub", sub)):
    for p in sorted((d / "answers").glob("*.json")):
        runs[f"{tag}_{p.stem}"] = {a["item_id"]: a["answer"] for a in json.loads(p.read_text(encoding="utf-8-sig"))}
state = {}
for kind in ("rate", "header", "heading"):
    d = json.loads((sub / "fwd" / f"blind_{kind}.json").read_text(encoding="utf-8"))
    for it in d["items"]:
        state[it["item_id"]] = it["state"]
n = 0
for i, r in ref.items():
    label = r["r1_ref"] if r["kind"] == "rate" else r["ref"]
    if r["basis"] != "strong":
        continue
    wrong = {k: v[i] for k, v in runs.items() if v.get(i) != label}
    if not wrong:
        continue
    n += 1
    s = {k: v for k, v in state[i].items() if not (isinstance(v, dict) and "see_shared" in v)}
    print(f"### {n} {r['kind']} {i} fund={r['fund']} LABEL={label} wrong_in={len(wrong)}/{len(runs)}")
    print("   answers:", wrong)
    print("   state:", json.dumps(s, ensure_ascii=True)[:900])
print("items with any miss:", n)
