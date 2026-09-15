"""Run a bounded, cache-only production-stack context inventory into scratch."""
from __future__ import annotations

import argparse
from decimal import Decimal
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.context_inventory import fund_quarter_class, scan_instance
from pipeline.programme.core import atomic_json, now, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--cik", required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--investment-total", type=Decimal)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    dest = args.output_dir.resolve()
    if not dest.is_relative_to(ROOT / "scratch"):
        parser.error("Context inventory output must be under scratch/")
    if (dest / "complete.json").exists():
        parser.error("Completed inventory is immutable; use a new output directory")
    dest.mkdir(parents=True, exist_ok=True)
    atomic_json(dest / "request.json", dict(cik=args.cik, quarter=args.quarter,
        instance=str(args.instance), started_utc=now(), pid=os.getpid(), timeout=None))
    print("Inspect cached instance: " + str(args.instance), flush=True)
    result = scan_instance(args.instance, args.cik, args.quarter)
    counts = result["counts"]
    result["zero_output_class"] = fund_quarter_class(complete=result["source_complete"],
        positions=counts["confirmed_position"], unresolved=counts["unresolved"],
        investment_total=args.investment_total)
    result["source_module_sha256"] = sha(ROOT / "pipeline/context_inventory.py")
    result["compatibility_module_sha256"] = sha(ROOT / "pipeline/bdc_filings.py")
    result["classification_scope"] = "eligible fund-quarter IF output is absent; not an eligibility finding"
    atomic_json(dest / "contexts.json", result)
    atomic_json(dest / "complete.json", dict(result_sha256=sha(dest / "contexts.json"), completed_utc=now()))
    print("Counts: " + str(counts) + "; complete=" + str(result["source_complete"]), flush=True)
    print("Zero-output class: " + result["zero_output_class"], flush=True)
    for error in result["errors"][:5]:
        print("Source issue: " + error, flush=True)
    return 0 if result["source_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
