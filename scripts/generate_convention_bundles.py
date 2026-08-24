"""Generate review bundles for convention-adjudicator targets lacking one.

The convention worklist (run_convention discover) marks CIK-quarters with
``bundle_path = NEEDS_BUNDLE``. Bundles are built by pipeline.review_bundles
from review-queue rows, so for each bundle-less target this script:

  1. picks a review-queue row for that CIK at the target quarter
     (preferring fv_conservation, the richest evidence mapping);
  2. writes a one-row temp queue under the batch dir;
  3. runs ``python -m pipeline.review_bundles --queue <tmp>`` -- per-CIK
     isolation so one odd filing cannot abort the batch (prepare_fresh_batch
     pattern).

After it finishes, re-run ``run_convention discover <new-batch-id>`` to pick
the fresh bundles up. Read-only outside data/output/review_queue and the
batch dir. ASCII-only.

    python -m scripts.generate_convention_bundles --batch-id probe_2026-07-21
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from pipeline import config

QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
BATCH_BASE = config.OUTPUT_DIR / "agent_convention" / "batch"


def _norm(c) -> str:
    return str(c or "").lstrip("0")


def _pick_queue_row(rows: list[dict], target_q: str) -> dict | None:
    """Prefer target-quarter fv_conservation, then any target-quarter row,
    then the latest row for the CIK. source_recon rows are excluded --
    pipeline.review_bundles intentionally does not handle that engine (it has
    the separate bdc_cik_review bundle path) and silently generates nothing."""
    rows = [r for r in rows if str(r.get("engine") or "") != "source_recon"]
    tq = str(target_q)[:10]
    at_q = [r for r in rows if str(r.get("report_date") or "")[:10] == tq]
    for pool in (at_q, rows):
        fv = [r for r in pool if str(r.get("rule_name") or "") == "fv_conservation"]
        if fv:
            return fv[0]
        if pool:
            return sorted(pool, key=lambda r: str(r.get("report_date") or ""),
                          reverse=True)[0]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate bundles for NEEDS_BUNDLE convention targets.")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--max-rows", type=int, default=25,
                    help="passed through to pipeline.review_bundles")
    args = ap.parse_args()

    wl_path = BATCH_BASE / args.batch_id / "convention_worklist.csv"
    if not wl_path.exists():
        print(f"worklist missing: {wl_path}")
        return 1
    with open(wl_path, newline="", encoding="utf-8-sig") as f:
        targets = [r for r in csv.DictReader(f)
                   if r.get("bundle_path") == "NEEDS_BUNDLE"]
    if not targets:
        print("no NEEDS_BUNDLE targets in worklist")
        return 0

    with open(QUEUE, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        qcols = rdr.fieldnames or []
        by_cik: dict[str, list[dict]] = {}
        for r in rdr:
            by_cik.setdefault(_norm(r.get("cik")), []).append(r)

    tmp_dir = BATCH_BASE / args.batch_id / "bundle_gen"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    ok, failed, no_row = [], [], []
    for i, t in enumerate(targets, 1):
        cik = _norm(t.get("cik"))
        tq = str(t.get("target_quarter") or "")
        row = _pick_queue_row(by_cik.get(cik, []), tq)
        if row is None:
            no_row.append(cik)
            print(f"[{i}/{len(targets)}] {cik} {tq}: NO queue row -- cannot bundle")
            continue
        tmp = tmp_dir / f"queue_{cik}.csv"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=qcols)
            w.writeheader()
            w.writerow(row)
        gen = subprocess.run(
            [sys.executable, "-m", "pipeline.review_bundles",
             "--queue", str(tmp), "--max-rows", str(args.max_rows)],
            capture_output=True, text=True)
        if gen.returncode == 0:
            ok.append(cik)
            print(f"[{i}/{len(targets)}] {cik} {tq}: bundle generated "
                  f"(from {row.get('rule_name')} @ {row.get('report_date')})",
                  flush=True)
        else:
            failed.append(cik)
            tail = (gen.stderr or gen.stdout or "").strip().splitlines()[-3:]
            print(f"[{i}/{len(targets)}] {cik} {tq}: FAILED\n  " + "\n  ".join(tail),
                  flush=True)

    print(f"DONE: {len(ok)} generated, {len(failed)} failed, {len(no_row)} without queue rows")
    if failed:
        print("failed ciks: " + ", ".join(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
