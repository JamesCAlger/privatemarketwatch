"""B-trial sampler: draw a stratified, HTML-cohort-filtered sample of queue rows.

Selects review-queue rows for the pilot's three rules (one per localization
class) restricted to CIKs that have cached BDC HTML (so the adjudicator can
actually roam raw source), and stratifies fv_conservation across residual-
magnitude buckets so the sample mixes textbook subtotal-leaks (small residual)
with anchor_bad cases (huge residual).

Writes a sampled_queue.csv (identical schema to review_queue.csv, so
`python -m pipeline.review_bundles --queue sampled_queue.csv` consumes it) plus
a sample_manifest.csv tagging each row with its localization class and bucket.

Deterministic: fixed random_state. Cache-only, read-only on production.

Usage:
    python scripts/review_agent/sample_bundles.py --n 15
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
FROZEN_Q = REPO / "data/output/shadow/trial_2026-06-18/frozen_registry/review_queue.csv"
BDC_HTML = REPO / "data/raw/filings/bdc_html"
OUT_DIR = REPO / "data/output/shadow/trial_2026-06-18/sample"

# rule_name -> localization class (per spec section 1)
PILOT_RULES = {
    "C113": "class1_single_cell",          # interest_rate outside range
    "pik_le_interest_rate": "class2_within_row",
    "fv_conservation": "class3_aggregate",
}
SEED = 20260619


def _html_cohort() -> set[int]:
    if not BDC_HTML.is_dir():
        return set()
    out = set()
    for name in os.listdir(BDC_HTML):
        p = BDC_HTML / name
        # require a non-empty dir so the filing is actually cached
        if p.is_dir() and any(p.iterdir()):
            try:
                out.add(int(name))
            except ValueError:
                continue
    return out


def _bucket(metric: float) -> str:
    m = abs(metric)
    if m < 5:
        return "small"
    if m < 25:
        return "mid"
    return "big"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sample queue rows for the B pilot.")
    ap.add_argument("--n", type=int, default=15, help="rows per rule")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    q = pd.read_csv(FROZEN_Q, dtype=str)
    q["_cik_int"] = pd.to_numeric(q["cik"], errors="coerce")
    cohort = _html_cohort()
    q = q[q["_cik_int"].isin(cohort)].copy()

    picks: list[pd.DataFrame] = []
    manifest_rows: list[dict] = []
    for rule, klass in PILOT_RULES.items():
        sub = q[q["rule_name"] == rule].copy()
        if sub.empty:
            print(f"WARN: no HTML-cohort rows for {rule}")
            continue
        if rule == "fv_conservation":
            sub["_metric"] = pd.to_numeric(sub["metric"], errors="coerce").fillna(0)
            sub["_bucket"] = sub["_metric"].map(_bucket)
            # even split across the three residual buckets
            per = max(1, args.n // 3)
            chosen = []
            for b in ("small", "mid", "big"):
                bs = sub[sub["_bucket"] == b]
                chosen.append(bs.sample(min(per, len(bs)), random_state=SEED))
            sel = pd.concat(chosen)
        else:
            sub["_bucket"] = "na"
            sel = sub.sample(min(args.n, len(sub)), random_state=SEED)
        sel["_class"] = klass
        picks.append(sel)
        for _, r in sel.iterrows():
            manifest_rows.append({
                "review_id": r["review_id"], "rule_name": rule, "klass": klass,
                "bucket": r.get("_bucket", "na"), "cik": r["cik"],
                "report_date": r["report_date"], "status": r["status"],
                "metric": r["metric"], "lane": r["lane"],
            })
        print(f"{rule:28} ({klass:20}): selected {len(sel)}")

    if not picks:
        print("ERROR: nothing selected")
        return 1

    out = pd.concat(picks)
    queue_cols = [c for c in out.columns if not c.startswith("_")]
    args.out.mkdir(parents=True, exist_ok=True)
    sampled_q = args.out / "sampled_queue.csv"
    out[queue_cols].to_csv(sampled_q, index=False)
    pd.DataFrame(manifest_rows).to_csv(args.out / "sample_manifest.csv", index=False)
    print(f"\nwrote {sampled_q} ({len(out)} rows)")
    print(f"wrote {args.out / 'sample_manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
