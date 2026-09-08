"""One-shot, idempotent backfill of `basis` on existing anchor leaves (spec 2026-09-07 s.2).

Deterministic rules, using only the leaf's own numbers:
  investments_ex_cash : grand_total within 0.5% of the leaf's companyfacts_fv
  published_rows      : grand_total > companyfacts_fv * 1.005 AND at least one component label
                        mentions cash / money market / short-term / treasury / sweep
  unresolved          : anything else (no companyfacts_fv, wider with no cash label, below the tag)
                        -> listed for the anchor lane; leaf left untouched (the gate ignores it).

    python scripts/backfill_anchor_basis.py [--dry-run] [--overrides-dir DIR] [--out CSV]
ASCII-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config                                   # noqa: E402
from pipeline.anchor_leaf import BASES, validate_anchor_leaf   # noqa: E402

_TOL = 0.005
_CASH_LABEL = re.compile(r"cash|money market|short-?term|treasur|sweep", re.I)
OUT_COLUMNS = ["cik", "target_quarter", "grand_total", "companyfacts_fv", "method", "reason"]


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def classify_leaf(leaf: dict) -> str:
    gt, cf = _num(leaf.get("grand_total")), _num(leaf.get("companyfacts_fv"))
    if gt is None or cf is None or cf <= 0:
        return ""
    if abs(gt - cf) <= _TOL * cf:
        return "investments_ex_cash"
    labels = " ".join(str(c.get("label") or "") for c in (leaf.get("components") or [])
                      if isinstance(c, dict))
    if gt > cf * (1 + _TOL) and _CASH_LABEL.search(labels):
        return "published_rows"
    return ""


def _reason(leaf: dict) -> str:
    gt, cf = _num(leaf.get("grand_total")), _num(leaf.get("companyfacts_fv"))
    if gt is None or cf is None or cf <= 0:
        return "no companyfacts_fv on leaf"
    if gt < cf * (1 - _TOL):
        return "grand_total below companyfacts tag"
    return "grand_total wider than companyfacts tag but no cash-like component label"


def backfill(overrides_dir: Path, out_csv: Path, *, write: bool) -> dict:
    counts = {"published_rows": 0, "investments_ex_cash": 0, "unresolved": 0,
              "already_set": 0, "invalid": 0}
    unresolved: list[dict] = []
    for p in sorted(Path(overrides_dir).glob("*/*.json")):
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            counts["invalid"] += 1
            continue
        if not isinstance(leaf, dict):
            counts["invalid"] += 1
            continue
        if str(leaf.get("basis") or "") in BASES:
            counts["already_set"] += 1
            continue
        basis = classify_leaf(leaf)
        if basis:
            candidate = {**leaf, "basis": basis}
            errs = [e for e in validate_anchor_leaf(candidate) if "mislabelled" in e]
            if errs:
                basis = ""
        if not basis:
            counts["unresolved"] += 1
            unresolved.append({"cik": str(leaf.get("cik") or p.parent.name).zfill(10),
                               "target_quarter": leaf.get("target_quarter") or p.stem,
                               "grand_total": leaf.get("grand_total"),
                               "companyfacts_fv": leaf.get("companyfacts_fv"),
                               "method": leaf.get("method"), "reason": _reason(leaf)})
            continue
        counts[basis] += 1
        if write:
            leaf["basis"] = basis
            p.write_text(json.dumps(leaf, indent=2), encoding="utf-8")
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(unresolved)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill anchor-leaf basis (spec 2026-09-07 s.2).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overrides-dir", type=Path, default=config.AGENT_ANCHOR_OVERRIDES_DIR)
    ap.add_argument("--out", type=Path,
                    default=config.OUTPUT_DIR / "agent_anchor" / "basis_backfill_unresolved.csv")
    a = ap.parse_args(argv)
    counts = backfill(a.overrides_dir, a.out, write=not a.dry_run)
    print(json.dumps({"dry_run": a.dry_run, "counts": counts, "unresolved_csv": str(a.out)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
