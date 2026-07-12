"""Prepare a B1 batch of FRESH cohort CIKs (no existing bundle): select N from the review queue,
GENERATE their review bundles, then build the B1 worklist (anchorable-only, null-anchor deferred).
The companion to build_b1_batch_from_bundles, which only selects from bundles that already exist.

    python -m scripts.prepare_fresh_batch --batch-id fresh1 --n 1 --exclude-cik 1715933,1603480,...

After this: dispatch B1 on <batch-id>, then run scripts/run_full_remediation_canary.ps1. ASCII-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from pipeline import config
from scripts.build_b1_batch_from_bundles import build

QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"


def _norm(c) -> str:
    return str(c or "").lstrip("0")


def _select_fresh(n: int, exclude: set[str]) -> list[dict]:
    """N distinct fv_conservation CIKs (latest quarter each) that are NOT excluded and have no B1
    verdict yet (whether or not a bundle already exists)."""
    with open(QUEUE, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if str(r.get("rule_name") or "") == "fv_conservation"]
    by_cik: dict[str, list[dict]] = {}
    for r in rows:
        cik = _norm(r.get("cik"))
        if cik and cik not in exclude:
            by_cik.setdefault(cik, []).append(r)
    picked: list[dict] = []
    for cik in sorted(by_cik):
        for r in sorted(by_cik[cik], key=lambda x: str(x.get("report_date") or ""), reverse=True):
            rid = (r.get("review_id") or "").strip()
            if rid and not (VERDICTS / f"{rid}.json").exists():        # no verdict -> runnable
                picked.append(r)
                break
        if len(picked) >= n:
            break
    return picked


def prepare(batch_id: str, *, n: int, exclude: set[str], include_null: bool = False) -> dict:
    fresh = _select_fresh(n, exclude)
    if not fresh:
        return {"batch_id": batch_id, "status": "no_fresh_ciks", "n_generated": 0}
    # Generate bundles PER-CIK so one odd filing cannot abort the whole batch (key for a large
    # unattended run): write a 1-row queue, generate, continue on failure.
    cols = None
    with open(QUEUE, newline="", encoding="utf-8-sig") as f:
        cols = csv.DictReader(f).fieldnames
    tmp = config.OUTPUT_DIR / "review_queue" / f"_fresh_queue.{batch_id}.csv"
    n_gen, gen_failed = 0, []
    for r in fresh:
        rid = (r.get("review_id") or "").strip()
        if rid and (BUNDLES / f"{rid}.json").exists():
            continue                                   # already has a bundle
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerow(r)
        gen = subprocess.run([sys.executable, "-m", "pipeline.review_bundles", "--queue", str(tmp),
                              "--output-dir", str(config.OUTPUT_DIR / "review_queue")],
                             capture_output=True, text=True)
        if gen.returncode == 0 and rid and (BUNDLES / f"{rid}.json").exists():
            n_gen += 1
        else:
            gen_failed.append(_norm(r.get("cik")))
    # build the B1 worklist from whatever bundles now exist (excluding the done set)
    res = build(batch_id, n=n, exclude_ciks=exclude, include_null=include_null)
    res["status"] = "ok"
    res["n_generated"] = n_gen
    res["gen_failed"] = gen_failed
    res["generated_for"] = [(_norm(r["cik"]), r.get("report_date")) for r in fresh]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prepare a B1 batch of fresh CIKs (generate bundles).")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--exclude-cik", default="")
    ap.add_argument("--include-null-anchor", action="store_true",
                    help="(b) include companyfacts-less quarters (anchor from the filing) instead of deferring")
    args = ap.parse_args(argv)
    excl = {_norm(c) for c in args.exclude_cik.split(",") if c.strip()}
    print(json.dumps(prepare(args.batch_id, n=args.n, exclude=excl,
                             include_null=args.include_null_anchor), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
