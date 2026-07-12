"""CLI: validate B2 correction-leaf files against the schema + template registry.

Thin wrapper over ``pipeline.correction_leaf``. This is the screen a B2 worker runs on its
own output (``--correction``) and the batch check the dispatcher runs over a corrections
directory (``--corrections-dir``). The analog of
``scripts/review_agent/validate_leaf_verdicts.py`` for verdicts.

Usage:
    python -m scripts.agent_b2.validate_corrections --correction path/to/<cik>/<fix_class>.json
    python -m scripts.agent_b2.validate_corrections --corrections-dir data/output/agent_b2/corrections
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline import correction_leaf  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Validate Agent B2 correction-leaf files.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--correction", type=Path, help="Validate a single correction file.")
    g.add_argument("--corrections-dir", type=Path, help="Validate every *.json under a dir.")
    p.add_argument("--expected-cik", default=None, help="Require the correction cik to match.")
    p.add_argument(
        "--expected-fix-class", default=None, help="Require the correction fix_class to match."
    )
    args = p.parse_args(argv)

    if args.correction is not None:
        try:
            obj = json.loads(args.correction.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"INVALID: unreadable/invalid JSON: {exc}", file=sys.stderr)
            return 1
        rep = correction_leaf.validate_correction(
            obj, expected_cik=args.expected_cik, expected_fix_class=args.expected_fix_class,
        )
        for w in rep.warnings:
            print(f"WARN  {rep.cik}/{rep.mechanism}: {w}")
        if rep.ok:
            print(f"OK    {rep.cik}/{rep.mechanism}")
            return 0
        for e in rep.errors:
            print(f"ERROR {rep.cik}/{rep.mechanism}: {e}", file=sys.stderr)
        return 1

    summary = correction_leaf.validate_dir(args.corrections_dir)
    for rep in summary["reports"]:
        for w in rep.warnings:
            print(f"WARN  {rep.cik}/{rep.mechanism}: {w}")
        for e in rep.errors:
            print(f"ERROR {rep.cik}/{rep.mechanism}: {e}", file=sys.stderr)
    print(f"\n{summary['n_valid']}/{summary['n_files']} valid; {summary['n_error_files']} with errors")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
