"""Read-only EDA over the B1 ens2 weak-rule adjudication batch.

Joins data/output/ensemble/ens2/review_ids.csv (metadata) to the B1 verdict
leaves in data/output/review_queue/verdicts/<rid>.json (adjudication) and prints
cross-tabs the analyze_ensemble.py derived tables do not cover: verdict x engine,
confidence distribution, escalate rate, per-CIK concentration, mechanism mix.

Read-only. No network. ASCII-only. Small dataset (~934 rows).
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

BATCH = Path("data/output/ensemble/ens2")
VERDICTS = Path("data/output/review_queue/verdicts")
DECIDED = {"real_error", "false_alarm"}


def load():
    rows = []
    with open(BATCH / "review_ids.csv", newline="", encoding="utf-8") as fh:
        meta = {r["review_id"]: r for r in csv.DictReader(fh)}
    for rid, m in meta.items():
        p = VERDICTS / f"{rid}.json"
        if not p.exists():
            continue
        try:
            v = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        verdict = (v.get("verdict") or "").strip().lower()
        basis = (v.get("ambiguity_basis") or "").strip().lower()
        if verdict == "ambiguous" and basis == "source_unavailable":
            verdict = "no_source"
        rows.append({
            "rid": rid, "cik": m["cik"], "engine": m["engine"],
            "rule": m["rule_name"], "stratum": m["stratum"],
            "date": m["report_date"], "verdict": verdict,
            "confidence": v.get("confidence"),
            "escalate": v.get("escalate"),
            "mechanism": (v.get("mechanism") or "").strip(),
        })
    return rows


def pct(n, d):
    return f"{100*n/d:5.1f}%" if d else "   n/a"


def main():
    rows = load()
    n = len(rows)
    print(f"=== ens2 adjudication EDA  (n={n} flags) ===\n")

    vc = Counter(r["verdict"] for r in rows)
    print("-- verdict mix --")
    for k, c in vc.most_common():
        print(f"  {k:12s} {c:4d}  {pct(c,n)}")
    decided = [r for r in rows if r["verdict"] in DECIDED]
    real = sum(1 for r in decided if r["verdict"] == "real_error")
    print(f"  decided={len(decided)}  pooled real-rate={pct(real,len(decided))} "
          f"pooled FP={pct(len(decided)-real,len(decided))}\n")

    print("-- verdict x engine (row% real of decided) --")
    eng = sorted({r["engine"] for r in rows})
    for e in eng:
        sub = [r for r in rows if r["engine"] == e]
        d = [r for r in sub if r["verdict"] in DECIDED]
        rr = sum(1 for r in d if r["verdict"] == "real_error")
        print(f"  {e:16s} n={len(sub):4d}  decided={len(d):4d}  real={pct(rr,len(d))}")
    print()

    print("-- confidence distribution (decided only) --")
    cc = Counter(str(r["confidence"]) for r in decided)
    for k, c in cc.most_common():
        print(f"  conf={k:8s} {c:4d}  {pct(c,len(decided))}")
    print()

    print("-- escalate flag --")
    esc = Counter(str(r["escalate"]) for r in rows)
    for k, c in esc.most_common():
        print(f"  escalate={k:6s} {c:4d}  {pct(c,n)}")
    print()

    print("-- top 12 CIKs by flag count (real-rate of decided) --")
    bycik = defaultdict(list)
    for r in rows:
        bycik[r["cik"]].append(r)
    for cik, sub in sorted(bycik.items(), key=lambda kv: -len(kv[1]))[:12]:
        d = [r for r in sub if r["verdict"] in DECIDED]
        rr = sum(1 for r in d if r["verdict"] == "real_error")
        print(f"  {cik}  flags={len(sub):3d}  decided={len(d):3d}  real={pct(rr,len(d))}")
    print(f"  distinct CIKs={len(bycik)}\n")

    print("-- top mechanisms (decided real_error only) --")
    mech = Counter(r["mechanism"][:48] for r in decided
                   if r["verdict"] == "real_error" and r["mechanism"])
    for k, c in mech.most_common(12):
        print(f"  {c:3d}  {k}")


if __name__ == "__main__":
    main()
