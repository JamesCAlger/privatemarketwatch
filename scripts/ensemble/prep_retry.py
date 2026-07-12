r"""Prepare a retry batch for the not-yet-decided review_ids of a prior ensemble batch.

After a partial/failed B1 run, this:
  1. scans the source batch's review_ids,
  2. KEEPS rids with a genuine verdict -- decided (real_error/false_alarm) or
     source_checked ambiguous,
  3. DELETES failed-run verdict files (auto, or ambiguous + source_unavailable) so B1
     preflight will not abort on a pre-existing verdict,
  4. writes <retry>/review_ids.csv = exactly the rids still needing adjudication,
     preserving the source columns so `discover --review-ids-from` consumes it directly.

Run ONLY after the prior dispatcher has stopped (no codex workers) -- it mutates the
shared verdicts dir. Then dispatch the retry as a NEW batch id (fresh worker_home dirs
=> no stale setup markers) at -MaxParallel 1 (no password race):

  python -m scripts.ensemble.prep_retry --src ens1_pilot --retry ens1_pilot_r2
  python -m scripts.agent_b.run_review discover ens1_pilot_r2 \
      --review-ids-from data/output/ensemble/ens1_pilot_r2/review_ids.csv
  python -m scripts.agent_b.dispatch_preflight --batch-id ens1_pilot_r2
  .\scripts\dispatch_agent_b_workers.ps1 -BatchId ens1_pilot_r2 -MaxParallel 1

Analysis still reads the FULL source batch (verdicts are shared by review_id):
  python -m scripts.ensemble.strip_verdict_bom --batch-id ens1_pilot
  python -m scripts.ensemble.analyze_ensemble --batch-id ens1_pilot

Read-only on the queue; deletes only failed verdicts; writes under data/output/ensemble.
No network. ASCII-only logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from pipeline import config

logger = logging.getLogger(__name__)

DEFAULT_OUT_BASE = config.OUTPUT_DIR / "ensemble"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"


def _state(path: Path) -> str:
    """decided | ambiguous_checked | failed | missing."""
    if not path.exists():
        return "missing"
    try:
        o = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "failed"  # unreadable/corrupt -> retry
    if o.get("auto") is True:
        return "failed"
    v = (o.get("verdict") or "").strip().lower()
    if v in {"real_error", "false_alarm"}:
        return "decided"
    if v == "ambiguous":
        return "failed" if (o.get("ambiguity_basis") or "").strip().lower() == "source_unavailable" else "ambiguous_checked"
    return "failed"


def prep(*, src_batch: str, retry_batch: str, verdicts_dir: Path) -> dict:
    src_dir = DEFAULT_OUT_BASE / src_batch
    with open(src_dir / "review_ids.csv", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or ["review_id"]
        rows = list(reader)

    keep_decided = keep_amb = deleted = 0
    retry_rows = []
    for r in rows:
        rid = r["review_id"]
        path = verdicts_dir / f"{rid}.json"
        st = _state(path)
        if st == "decided":
            keep_decided += 1
        elif st == "ambiguous_checked":
            keep_amb += 1
        else:  # failed | missing -> retry
            if st == "failed" and path.exists():
                path.unlink()
                deleted += 1
            retry_rows.append(r)

    retry_dir = DEFAULT_OUT_BASE / retry_batch
    retry_dir.mkdir(parents=True, exist_ok=True)
    with open(retry_dir / "review_ids.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(retry_rows)

    return {
        "src_total": len(rows),
        "kept_decided": keep_decided,
        "kept_ambiguous_checked": keep_amb,
        "failed_verdicts_deleted": deleted,
        "retry_count": len(retry_rows),
        "retry_review_ids": str(retry_dir / "review_ids.csv"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Prep a retry batch for a prior ensemble batch's undecided review_ids.")
    p.add_argument("--src", default="ens1_pilot")
    p.add_argument("--retry", default=None, help="Retry batch id (default: <src>_r2).")
    p.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    retry = args.retry or f"{args.src}_r2"
    res = prep(src_batch=args.src, retry_batch=retry, verdicts_dir=args.verdicts_dir)
    logger.info("source %s: %d rids | kept decided=%d, ambiguous(checked)=%d",
                args.src, res["src_total"], res["kept_decided"], res["kept_ambiguous_checked"])
    logger.info("deleted %d failed verdict(s); RETRY set = %d rids -> %s",
                res["failed_verdicts_deleted"], res["retry_count"], res["retry_review_ids"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
