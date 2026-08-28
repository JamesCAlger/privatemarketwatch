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
    p.add_argument(
        "--verify-source", action="store_true",
        help="For source_anchored_value leaves, re-parse the cached filing and verify "
             "every assertion (cell value, quoted text, row-fingerprint witnesses, "
             "table health, bridge co-sign). Cache-only; fail closed.")
    p.add_argument("--holdings", type=Path, default=None,
                   help="Holdings frame for witness verification (default: unified parquet).")
    p.add_argument("--verify-baseline", action="store_true",
                   help="For missing_position_add, refuse source_row_ids already represented "
                        "in the current unified holdings baseline. Cache-only; fail closed.")
    args = p.parse_args(argv)

    if args.correction is not None:
        # Escalation-aware (2026-08-21): a worker may write <fix_class>.escalation.json
        # INSTEAD of the correction when the binding fix_class cannot express the
        # verified defect. Resolve which artifact exists, then validate it with the
        # matching schema. An escalation validates as ESCALATED (exit 0) -- the
        # dispatcher routes it; it is never applied to data.
        path = args.correction
        is_escalation = path.name.endswith(correction_leaf.ESCALATION_SUFFIX)
        if not is_escalation and not path.exists():
            sibling = path.with_name(path.stem + correction_leaf.ESCALATION_SUFFIX)
            if sibling.exists():
                path, is_escalation = sibling, True
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"INVALID: unreadable/invalid JSON: {exc}", file=sys.stderr)
            return 1
        if is_escalation:
            rep = correction_leaf.validate_escalation(
                obj, expected_cik=args.expected_cik, expected_fix_class=args.expected_fix_class,
            )
        else:
            rep = correction_leaf.validate_correction(
                obj, expected_cik=args.expected_cik, expected_fix_class=args.expected_fix_class,
            )
        for w in rep.warnings:
            print(f"WARN  {rep.cik}/{rep.mechanism}: {w}")
        if rep.ok and not is_escalation and args.verify_source \
                and str(obj.get("fix_class")) == "source_anchored_value":
            from pipeline.source_anchor_verify import verify_leaf
            vrep = verify_leaf(obj, holdings_path=args.holdings)
            if not vrep["ok"]:
                for e in vrep["errors"]:
                    print(f"ERROR {rep.cik}/{rep.mechanism}: source-verify: {e}",
                          file=sys.stderr)
                return 1
            print(f"SOURCE-VERIFIED {rep.cik}/{rep.mechanism} "
                  f"({len(vrep['checks'])} assertion(s))")
        if rep.ok and not is_escalation and args.verify_baseline \
                and str(obj.get("fix_class")) == "missing_position_add":
            import pandas as pd
            from pipeline import config
            from pipeline.agent_b2_appliers import missing_position_source_collisions

            holdings_path = args.holdings or config.UNIFIED_HOLDINGS_PARQUET_FILE
            if not holdings_path.exists():
                print(f"ERROR {rep.cik}/{rep.mechanism}: baseline holdings unavailable: {holdings_path}",
                      file=sys.stderr)
                return 1
            frame = (pd.read_parquet(holdings_path) if holdings_path.suffix == ".parquet"
                     else pd.read_csv(holdings_path, low_memory=False))
            if "cik" not in frame.columns:
                print(f"ERROR {rep.cik}/{rep.mechanism}: baseline has no cik column", file=sys.stderr)
                return 1
            cik = str(obj.get("cik") or "").lstrip("0") or "0"
            frame = frame[frame["cik"].astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0").eq(cik)]
            collisions = missing_position_source_collisions(
                frame, list((obj.get("template") or {}).get("positions") or []))
            if collisions:
                print(f"ERROR {rep.cik}/{rep.mechanism}: source_row_id(s) already present "
                      f"in baseline: {collisions}", file=sys.stderr)
                return 1
            print(f"BASELINE-ABSENT {rep.cik}/{rep.mechanism}")
        if rep.ok:
            print(f"{'ESCALATED' if is_escalation else 'OK'}    {rep.cik}/{rep.mechanism}")
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
