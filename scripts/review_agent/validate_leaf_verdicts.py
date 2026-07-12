"""CLI: validate verdict-LEAF files (Agent B1) against the schema + grounding invariant.

Thin wrapper over ``pipeline.verdict_leaf``. This is the screen a B1 worker runs on its
own output (``--verdict``) and the batch check ``run_review finalize`` runs over a
verdicts directory (``--verdicts-dir``). Distinct from
``scripts/bdc_cik_review/validate_verdicts.py``, which validates the OLDER
patch-proposal schema (different lineage).

Usage:
    python -m scripts.review_agent.validate_leaf_verdicts --verdict path/to/RVQ_x.json
    python -m scripts.review_agent.validate_leaf_verdicts --verdicts-dir data/output/review_queue/verdicts
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import verdict_leaf  # noqa: E402


def _worklist_ids(path: Path) -> set[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["review_id"] for r in csv.DictReader(f) if r.get("review_id")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate Agent B1 verdict-leaf files.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--verdict", type=Path, help="Validate a single verdict file.")
    g.add_argument("--verdicts-dir", type=Path, help="Validate every *.json in a directory.")
    parser.add_argument("--worklist", type=Path, default=None,
                        help="Optional worklist.csv; enforce review_id membership + completeness.")
    args = parser.parse_args(argv)

    expected = _worklist_ids(args.worklist) if args.worklist else None

    if args.verdict is not None:
        try:
            obj = json.loads(args.verdict.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"INVALID: unreadable/invalid JSON: {exc}", file=sys.stderr)
            return 1
        rep = verdict_leaf.validate_verdict(obj, known_review_ids=expected)
        for w in rep.warnings:
            print(f"WARN  {rep.review_id}: {w}")
        if rep.ok:
            print(f"OK    {rep.review_id}")
            return 0
        for e in rep.errors:
            print(f"ERROR {rep.review_id}: {e}", file=sys.stderr)
        return 1

    summary = verdict_leaf.validate_dir(args.verdicts_dir, expected_review_ids=expected)
    for rep in summary["reports"]:
        for w in rep.warnings:
            print(f"WARN  {rep.review_id}: {w}")
        for e in rep.errors:
            print(f"ERROR {rep.review_id}: {e}", file=sys.stderr)
    for ce in summary["cross_errors"]:
        print(f"ERROR (cross): {ce}", file=sys.stderr)
    print(f"\n{summary['n_valid']}/{summary['n_files']} valid; "
          f"{summary['n_error_files']} with errors; {len(summary['cross_errors'])} cross-errors")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
