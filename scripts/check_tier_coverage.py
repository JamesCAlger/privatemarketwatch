"""Tier coverage checker: prove every frozen-slice item went through Agent B.

Joins a frozen tier slice (any CSV with a review_id column) against the two
verdict stores plus an optional operator-maintained residuals file, classifies
every item, and exits nonzero if any item is unaccounted for. This is the
mechanical gate between campaign tiers: do not dispatch tier N+1 until this
exits 0 for tier N.

Accounted-for means exactly one of:
  1. a VALID verdict JSON in data/output/review_queue/verdicts/ or
     data/output/bdc_cik_review/verdicts/ (valid = parses, has a verdict field
     in the allowed vocabulary, and any embedded review_id matches the
     filename -- catches truncated/corrupt worker output);
  2. a row in the --residuals CSV (review_id,reason) documenting a mechanical
     failure that survived the retry protocol.

Writes <slice>.coverage.csv with per-item status. The MISSING remainder is the
retry worklist. Read-only on production artifacts.

Usage:
  python scripts/check_tier_coverage.py --slice data/output/review_queue/_tier0.csv
  python scripts/check_tier_coverage.py --slice ... --residuals batch_residuals.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERDICT_DIRS = (
    ROOT / "data" / "output" / "review_queue" / "verdicts",
    ROOT / "data" / "output" / "bdc_cik_review" / "verdicts",
)

# B1 verdict vocabulary across both stores. review_queue uses the adjudication
# style (real_error/false_alarm/ambiguous/anchor_bad); bdc_cik_review uses
# PATCH_PROPOSED/NO_PATCH_NEEDED/INSUFFICIENT_EVIDENCE/ESCALATE (measured
# 2026-07-24: 48/15/1175/13). INSUFFICIENT_EVIDENCE counts as accounted-for
# (the item went through B and fail-closed on missing source), but implies an
# evidence/caching backlog item -- it is surfaced separately in the summary.
ALLOWED_VERDICTS = {
    "real_error",
    "false_alarm",
    "ambiguous",
    "anchor_bad",
    "PATCH_PROPOSED",
    "NO_PATCH_NEEDED",
    "INSUFFICIENT_EVIDENCE",
    "ESCALATE",
}


def load_verdict(path: Path) -> tuple[str, str]:
    """Return (status, detail) for one verdict file.

    status: 'verdict_<value>' when valid, 'invalid_verdict' otherwise.
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return "invalid_verdict", f"unreadable: {exc}"
    if not raw.strip():
        return "invalid_verdict", "empty file"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return "invalid_verdict", f"bad json: {exc}"
    verdict = data.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        return "invalid_verdict", f"verdict not in vocabulary: {verdict!r}"
    embedded = data.get("review_id")
    if embedded and embedded != path.stem:
        return "invalid_verdict", f"embedded id {embedded} != filename {path.stem}"
    # 2026-05-28 full-pool accounting pass: 1,174 placeholder verdicts were
    # auto-drafted (reviewer_notes marker) without any agent examining the
    # packet. They are bookkeeping, not adjudication -- count as NOT covered.
    notes = str(data.get("reviewer_notes") or "")
    if notes.startswith("Auto-drafted"):
        return "placeholder_autodrafted", "2026-05-28 full-pool accounting draft"
    # 2026-07-24 q4t0 lesson: ambiguous/source_unavailable means the worker could
    # not READ the raw source (cache miss / infra) -- a coverage state routed to
    # retry by finalize, not an adjudication. Same for auto B0 short-circuits.
    # Counting these as covered would close a tier no agent actually examined.
    if data.get("auto") or (verdict == "ambiguous"
                            and data.get("ambiguity_basis") == "source_unavailable"):
        return "no_source_not_covered", "ambiguous/source_unavailable or auto verdict"
    return f"verdict_{verdict}", ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slice", required=True, type=Path,
                    help="frozen tier slice CSV (must have a review_id column)")
    ap.add_argument("--residuals", type=Path, default=None,
                    help="operator residuals CSV (review_id,reason)")
    ap.add_argument("--out", type=Path, default=None,
                    help="coverage report path (default: <slice>.coverage.csv)")
    args = ap.parse_args()

    if not args.slice.exists():
        print(f"ERROR: slice not found: {args.slice}")
        return 2
    with open(args.slice, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows or "review_id" not in rows[0]:
        print("ERROR: slice has no rows or no review_id column")
        return 2

    residuals: dict[str, str] = {}
    if args.residuals and args.residuals.exists():
        with open(args.residuals, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rid = (r.get("review_id") or "").strip()
                reason = (r.get("reason") or "").strip()
                if rid and reason:
                    residuals[rid] = reason
                elif rid:
                    print(f"WARNING: residual {rid} has no reason; ignored")

    out_path = args.out or args.slice.with_suffix(".coverage.csv")
    counts: dict[str, int] = {}
    missing: list[str] = []
    report_rows = []

    for row in rows:
        rid = row["review_id"].strip()
        status, detail = "MISSING", ""
        for vdir in VERDICT_DIRS:
            vpath = vdir / f"{rid}.json"
            if vpath.exists():
                status, detail = load_verdict(vpath)
                if status != "invalid_verdict":
                    detail = vdir.name if detail == "" else detail
                break
        if status in ("MISSING", "invalid_verdict", "placeholder_autodrafted",
                      "no_source_not_covered") and rid in residuals:
            status, detail = "residual_documented", residuals[rid]
        if status in ("MISSING", "invalid_verdict", "placeholder_autodrafted",
                      "no_source_not_covered"):
            missing.append(rid)
        counts[status] = counts.get(status, 0) + 1
        report_rows.append(
            {"review_id": rid, "status": status, "detail": detail,
             "engine": row.get("engine", ""), "rule_name": row.get("rule_name", ""),
             "cik": row.get("cik", "")}
        )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
        w.writeheader()
        w.writerows(report_rows)

    print(f"slice: {args.slice.name} ({len(rows)} items)")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")
    print(f"report: {out_path}")

    if missing:
        print(f"REMAINDER: {len(missing)} items unaccounted for "
              f"(first 10): {', '.join(missing[:10])}")
        print("Tier is NOT closed. Route remainder to prep_retry or document "
              "in the residuals file with a reason.")
        return 1
    print("Tier CLOSED: every item has a valid verdict or a documented residual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
