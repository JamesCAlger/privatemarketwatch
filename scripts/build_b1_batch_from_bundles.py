"""Build a B1 batch worklist from EXISTING fv_conservation review bundles -- the prerequisite for
running the B1->B2->anchor->B2 chain on a fresh set of cohort CIKs without rebuilding the review
queue. Selects up to N distinct CIKs whose bundles already exist, excluding ones already done /
already in another batch, and writes data/output/agent_b/batch/<batch_id>/worklist.csv.

    python scripts/build_b1_batch_from_bundles.py --batch-id trial10 --n 10 \
        --exclude-cik 1715933,1603480,1743415 --exclude-batch canary_b1_to_b2_20260626T125839Z

Annotates each pick with the cheap incomplete-anchor screen (companyfacts_fv / total_assets) so you
can see up front which are likely anchor-adjudicator cases. ASCII-only. Cache-only.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pipeline import config
from scripts.agent_anchor.run_anchor import fund_financials
from pipeline.anchor_validation import incomplete_anchor_screen

BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
B1_BASE = config.OUTPUT_DIR / "agent_b" / "batch"
_COLS = ["review_id", "engine", "lane", "cik", "report_date", "rule_name", "class_hint", "bundle_path"]


def _norm(c) -> str:
    return str(c or "").lstrip("0")


def _batch_ciks(batch_id: str) -> set[str]:
    wl = B1_BASE / batch_id / "worklist.csv"
    out: set[str] = set()
    if wl.exists():
        with open(wl, newline="", encoding="utf-8-sig") as f:
            out = {_norm(r.get("cik")) for r in csv.DictReader(f)}
    return out


def _candidates(exclude_ciks: set[str]) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(BUNDLES.glob("*.json")) if BUNDLES.exists() else []:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(b.get("rule_name") or "") != "fv_conservation":
            continue
        cik = _norm(b.get("cik"))
        if not cik or cik in exclude_ciks:
            continue
        rid = (b.get("review_id") or "").strip()
        # Skip items B1 has ALREADY adjudicated: a worklist with any verdict-having item aborts the
        # WHOLE B1 preflight ("verdict already exists"), which starves the chain (the fresh50 bug).
        if rid and (VERDICTS / f"{rid}.json").exists():
            continue
        rows.append({"review_id": rid, "cik": cik,
                     "report_date": str(b.get("report_date") or ""), "bundle": p})
    return rows


def _has_anchor(ff: dict) -> bool:
    return ff.get("companyfacts_fv") is not None and ff.get("total_assets") is not None


def build(batch_id: str, *, n: int, exclude_ciks: set[str], include_null: bool = False) -> dict:
    cands = _candidates(exclude_ciks)
    by_cik: dict[str, list[dict]] = {}
    for r in cands:
        by_cik.setdefault(r["cik"], []).append(r)

    picked: list[tuple[dict, dict]] = []        # (bundle row, fund_financials for its quarter)
    deferred: list[dict] = []                   # cik-quarters with NO companyfacts anchor (can't validate)
    for cik in sorted(by_cik):
        ffc = fund_financials(cik)
        # (a) prefer the latest quarter that HAS a companyfacts anchor.
        chosen = None
        for r in sorted(by_cik[cik], key=lambda x: x["report_date"], reverse=True):
            ff = ffc.get(r["report_date"], {})
            if _has_anchor(ff):
                chosen = (r, ff)
                break
        if chosen is None:
            if include_null:
                # (b) no companyfacts anchor -> still include the LATEST quarter; the anchor-
                # adjudicator will source the anchor from the filing (MEDIUM, filing-sourced).
                r = sorted(by_cik[cik], key=lambda x: x["report_date"], reverse=True)[0]
                chosen = (r, ffc.get(r["report_date"], {}))
            else:
                for r in by_cik[cik]:
                    deferred.append({"cik": cik, "report_date": r["report_date"],
                                     "reason": "no companyfacts anchor (defer until data refresh)"})
                continue
        picked.append(chosen)
        if len(picked) >= n:
            break

    out_dir = B1_BASE / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    wl = out_dir / "worklist.csv"
    with open(wl, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COLS)
        w.writeheader()
        for r, _ff in picked:
            rel = r["bundle"].relative_to(config.PROJECT_ROOT).as_posix()
            w.writerow({"review_id": r["review_id"], "engine": "conservation", "lane": "blocker",
                        "cik": r["cik"], "report_date": r["report_date"],
                        "rule_name": "fv_conservation", "class_hint": "class3_aggregate",
                        "bundle_path": rel})
    # annotate with the (cash-aware) incomplete-anchor screen for visibility
    annotated = []
    for r, ff in picked:
        flagged, reason = incomplete_anchor_screen(ff.get("companyfacts_fv"), ff.get("total_assets"), ff.get("cash"))
        annotated.append({"cik": r["cik"], "report_date": r["report_date"],
                          "anchor_screen": "FLAG" if flagged else "ok", "screen_reason": reason,
                          "companyfacts_fv": ff.get("companyfacts_fv"), "total_assets": ff.get("total_assets"),
                          "cash": ff.get("cash")})
    return {"batch_id": batch_id, "n_picked": len(picked), "worklist": str(wl), "targets": annotated,
            "n_deferred": len(deferred), "deferred": deferred}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a B1 batch worklist from existing bundles.")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--exclude-cik", default="", help="comma-separated CIKs to skip")
    ap.add_argument("--exclude-batch", default="", help="skip CIKs already in this batch")
    ap.add_argument("--include-null-anchor", action="store_true",
                    help="(b) include companyfacts-less quarters (anchor them from the filing) instead of deferring")
    args = ap.parse_args(argv)
    excl = {_norm(c) for c in args.exclude_cik.split(",") if c.strip()}
    if args.exclude_batch:
        excl |= _batch_ciks(args.exclude_batch)
    res = build(args.batch_id, n=args.n, exclude_ciks=excl, include_null=args.include_null_anchor)
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
