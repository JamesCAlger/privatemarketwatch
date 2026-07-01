"""Aggregate B-trial verdicts: persist + per-rule counts with Wilson CIs.

Reads the workflow output JSON (the {result:[...verdicts]} object), writes each
verdict to verdicts/<review_id>.json, joins to the sample manifest by review_id,
and prints per-rule real_error / false_alarm / ambiguous counts plus a Wilson 95%
CI on the false-alarm rate among DECIDED (real_error+false_alarm) verdicts.

NOTE: agent-relative (no human gold slice yet) -> provisional precision.

Usage:
    python scripts/review_agent/aggregate_verdicts.py <workflow_output.json>
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRIAL = REPO / "data/output/shadow/trial_2026-06-18"
VERDICTS = TRIAL / "verdicts"
MANIFEST = TRIAL / "sample/sample_manifest.csv"


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)


def main() -> int:
    out_path = Path(sys.argv[1])
    blob = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
    verdicts = blob.get("result") or blob
    man = {r["review_id"]: r for r in csv.DictReader(open(MANIFEST))}

    VERDICTS.mkdir(parents=True, exist_ok=True)
    by_rule = defaultdict(lambda: defaultdict(int))
    loc = defaultdict(int)
    for v in verdicts:
        rid = v.get("review_id")
        m = man.get(rid, {})
        rule = m.get("rule_name", "?")
        (VERDICTS / f"{rid}.json").write_text(json.dumps(v, indent=2))
        by_rule[rule][v.get("verdict", "?")] += 1
        by_rule[rule]["_n"] += 1
        if v.get("localized"):
            loc[rule] += 1

    print(f"persisted {len(verdicts)} verdicts to {VERDICTS}\n")
    hdr = f"{'rule':24}{'n':>3}{'real':>6}{'false':>6}{'amb':>5}{'loc':>5}  false_alarm_rate (Wilson95 of decided)"
    print(hdr)
    print("-" * len(hdr))
    for rule in sorted(by_rule):
        c = by_rule[rule]
        n = c["_n"]
        real = c.get("real_error", 0)
        false = c.get("false_alarm", 0)
        amb = c.get("ambiguous", 0)
        decided = real + false
        p, lo, hi = wilson(false, decided)
        rate = "n/a" if decided == 0 else f"{p:.0%}  [{lo:.0%}, {hi:.0%}]  (n_decided={decided})"
        print(f"{rule:24}{n:>3}{real:>6}{false:>6}{amb:>5}{loc[rule]:>5}  {rate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
