"""Normalize verdict JSON files to UTF-8 without BOM, in place.

Codex workers on Windows sometimes write the verdict leaf with a UTF-8 BOM. The
UNMODIFIED Agent B1 finalize (scripts/agent_b/run_review.py) reads verdicts with
strict utf-8 and crashes on a BOM ("Unexpected UTF-8 BOM"). Rather than amend B1,
run this normalizer over a batch's verdict files BEFORE `run_review finalize`.

Content is preserved byte-for-byte except the leading BOM is removed (re-encoded
utf-8 no-BOM). Operates only on the review_ids of the given ensemble batch, so it
touches nothing outside the experiment's own verdicts. Idempotent. ASCII-only logs.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from pipeline import config

logger = logging.getLogger(__name__)

DEFAULT_OUT_BASE = config.OUTPUT_DIR / "ensemble"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
BOM = b"\xef\xbb\xbf"


def strip_batch(batch_id: str, verdicts_dir: Path) -> dict:
    review_ids_csv = DEFAULT_OUT_BASE / batch_id / "review_ids.csv"
    with open(review_ids_csv, newline="", encoding="utf-8") as fh:
        rids = [r["review_id"] for r in csv.DictReader(fh)]

    present = stripped = 0
    for rid in rids:
        path = verdicts_dir / f"{rid}.json"
        if not path.exists():
            continue
        present += 1
        data = path.read_bytes()
        if data.startswith(BOM):
            path.write_bytes(data[len(BOM):])
            stripped += 1
    return {"review_ids": len(rids), "verdicts_present": present, "bom_stripped": stripped}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Strip UTF-8 BOM from a batch's verdict files (pre-finalize fixup).")
    p.add_argument("--batch-id", default="ens1_pilot")
    p.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = strip_batch(args.batch_id, args.verdicts_dir)
    logger.info("batch %s: %d review_ids, %d verdicts present, %d BOMs stripped",
                args.batch_id, res["review_ids"], res["verdicts_present"], res["bom_stripped"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
